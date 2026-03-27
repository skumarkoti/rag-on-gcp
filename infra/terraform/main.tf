terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Uncomment to use GCS as a remote backend:
  # backend "gcs" {
  #   bucket = "your-terraform-state-bucket"
  #   prefix = "rag-on-gcp/terraform.tfstate"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

locals {
  name_prefix = "${var.app_name}-${var.environment}"
  image_uri   = "${var.region}-docker.pkg.dev/${var.project_id}/${var.app_name}/${var.app_name}:${var.image_tag}"

  common_labels = {
    app         = var.app_name
    environment = var.environment
    managed_by  = "terraform"
  }
}

# ═══════════════════════════════════════════════════════════════════════════════
# APIs — Enable required GCP services
# ═══════════════════════════════════════════════════════════════════════════════

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "storage.googleapis.com",
    "aiplatform.googleapis.com",
    "secretmanager.googleapis.com",
    "vpcaccess.googleapis.com",
    "redis.googleapis.com",
    "cloudtasks.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "cloudtrace.googleapis.com",
  ])

  service            = each.value
  disable_on_destroy = false
}

# ═══════════════════════════════════════════════════════════════════════════════
# Service Account
# ═══════════════════════════════════════════════════════════════════════════════

resource "google_service_account" "rag_sa" {
  account_id   = "${local.name_prefix}-sa"
  display_name = "RAG on GCP Service Account"
  description  = "Runtime identity for the RAG Cloud Run service"
  depends_on   = [google_project_service.apis]
}

# Minimal IAM roles required by the application
resource "google_project_iam_member" "rag_sa_roles" {
  for_each = toset([
    "roles/storage.objectAdmin",         # Read/write PDFs and ChromaDB snapshots
    "roles/aiplatform.user",             # Call Vertex AI embedding + Gemini APIs
    "roles/secretmanager.secretAccessor", # Read secrets at runtime
    "roles/logging.logWriter",           # Write structured logs to Cloud Logging
    "roles/cloudtrace.agent",            # Write traces to Cloud Trace
    "roles/monitoring.metricWriter",     # Write custom metrics
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.rag_sa.email}"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Artifact Registry — Docker image repository
# ═══════════════════════════════════════════════════════════════════════════════

resource "google_artifact_registry_repository" "rag_repo" {
  location      = var.region
  repository_id = var.app_name
  format        = "DOCKER"
  description   = "Docker images for ${var.app_name}"
  labels        = local.common_labels
  depends_on    = [google_project_service.apis]
}

# ═══════════════════════════════════════════════════════════════════════════════
# Cloud Storage — PDFs and ChromaDB persistence
# ═══════════════════════════════════════════════════════════════════════════════

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "google_storage_bucket" "rag_bucket" {
  name          = "${local.name_prefix}-data-${random_id.bucket_suffix.hex}"
  location      = var.gcs_location
  storage_class = var.gcs_storage_class
  labels        = local.common_labels

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  lifecycle_rule {
    action { type = "Delete" }
    condition {
      num_newer_versions = 3
      with_state         = "ARCHIVED"
    }
  }

  # Auto-delete stale ChromaDB snapshots after 30 days
  lifecycle_rule {
    action { type = "Delete" }
    condition {
      age    = 30
      prefix = "chroma/"
    }
  }

  depends_on = [google_project_service.apis]
}

# ═══════════════════════════════════════════════════════════════════════════════
# Networking — VPC and Serverless VPC Access connector (for Redis)
# ═══════════════════════════════════════════════════════════════════════════════

resource "google_compute_network" "rag_vpc" {
  name                    = "${local.name_prefix}-vpc"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

resource "google_compute_subnetwork" "rag_subnet" {
  name          = "${local.name_prefix}-subnet"
  ip_cidr_range = "10.0.0.0/24"
  region        = var.region
  network       = google_compute_network.rag_vpc.id
}

resource "google_vpc_access_connector" "rag_connector" {
  name          = "${var.app_name}-connector"
  region        = var.region
  ip_cidr_range = var.vpc_connector_cidr
  network       = google_compute_network.rag_vpc.name
  min_instances = 2
  max_instances = 3
  depends_on    = [google_project_service.apis]
}

# ═══════════════════════════════════════════════════════════════════════════════
# Redis (Cloud Memorystore) — Query result cache
# ═══════════════════════════════════════════════════════════════════════════════

resource "google_redis_instance" "rag_cache" {
  count = var.enable_redis ? 1 : 0

  name               = "${local.name_prefix}-cache"
  tier               = "BASIC"
  memory_size_gb     = var.redis_memory_size_gb
  region             = var.region
  authorized_network = google_compute_network.rag_vpc.id
  redis_version      = "REDIS_7_0"
  display_name       = "RAG Query Cache"
  labels             = local.common_labels

  depends_on = [google_project_service.apis]
}

# ═══════════════════════════════════════════════════════════════════════════════
# Secret Manager — Store sensitive config
# ═══════════════════════════════════════════════════════════════════════════════

resource "google_secret_manager_secret" "grafana_password" {
  count     = var.enable_grafana ? 1 : 0
  secret_id = "${local.name_prefix}-grafana-password"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "grafana_password" {
  count       = var.enable_grafana ? 1 : 0
  secret      = google_secret_manager_secret.grafana_password[0].id
  secret_data = var.grafana_password
}

# ═══════════════════════════════════════════════════════════════════════════════
# Cloud Run — RAG Application
# ═══════════════════════════════════════════════════════════════════════════════

resource "google_cloud_run_v2_service" "rag_app" {
  name     = local.name_prefix
  location = var.region
  labels   = local.common_labels

  deletion_protection = false

  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.rag_sa.email

    scaling {
      min_instance_count = var.cloud_run_min_instances
      max_instance_count = var.cloud_run_max_instances
    }

    max_instance_request_concurrency = var.cloud_run_concurrency

    timeout = "${var.cloud_run_timeout}s"

    vpc_access {
      connector = google_vpc_access_connector.rag_connector.id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = local.image_uri
      name  = var.app_name

      resources {
        limits = {
          cpu    = var.cloud_run_cpu
          memory = var.cloud_run_memory
        }
        cpu_idle          = false  # Keep CPU allocated between requests for better latency
        startup_cpu_boost = true   # Extra CPU during container startup
      }

      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "GCP_REGION"
        value = var.region
      }
      env {
        name  = "GCS_BUCKET_NAME"
        value = google_storage_bucket.rag_bucket.name
      }
      env {
        name  = "VERTEX_AI_LOCATION"
        value = var.vertex_ai_location
      }
      env {
        name  = "EMBEDDING_MODEL"
        value = var.embedding_model
      }
      env {
        name  = "LLM_MODEL"
        value = var.llm_model
      }
      env {
        name  = "CHROMA_SYNC_TO_GCS"
        value = "true"
      }
      env {
        name  = "METRICS_ENABLED"
        value = "true"
      }
      env {
        name  = "LOG_LEVEL"
        value = var.environment == "production" ? "INFO" : "DEBUG"
      }
      # Redis URL (only set when Redis is enabled)
      dynamic "env" {
        for_each = var.enable_redis ? [1] : []
        content {
          name  = "REDIS_URL"
          value = "redis://${google_redis_instance.rag_cache[0].host}:${google_redis_instance.rag_cache[0].port}"
        }
      }

      ports {
        container_port = 8080
        name           = "http1"
      }

      startup_probe {
        http_get {
          path = "/api/v1/health/live"
          port = 8080
        }
        initial_delay_seconds = 10
        timeout_seconds       = 5
        period_seconds        = 5
        failure_threshold     = 6  # 30s total startup window
      }

      liveness_probe {
        http_get {
          path = "/api/v1/health/live"
          port = 8080
        }
        initial_delay_seconds = 30
        timeout_seconds       = 5
        period_seconds        = 15
        failure_threshold     = 3
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_artifact_registry_repository.rag_repo,
    google_storage_bucket.rag_bucket,
    google_project_iam_member.rag_sa_roles,
    google_vpc_access_connector.rag_connector,
  ]
}

# Allow unauthenticated public access (remove for internal-only deployments)
resource "google_cloud_run_v2_service_iam_member" "rag_public" {
  location = google_cloud_run_v2_service.rag_app.location
  name     = google_cloud_run_v2_service.rag_app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ═══════════════════════════════════════════════════════════════════════════════
# Cloud Run — Grafana (optional monitoring UI)
# ═══════════════════════════════════════════════════════════════════════════════

resource "google_cloud_run_v2_service" "grafana" {
  count    = var.enable_grafana ? 1 : 0
  name     = "${local.name_prefix}-grafana"
  location = var.region
  labels   = local.common_labels

  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.rag_sa.email

    scaling {
      min_instance_count = 1
      max_instance_count = 1
    }

    containers {
      image = "grafana/grafana:11.2.0"
      name  = "grafana"

      resources {
        limits = {
          cpu    = "1000m"
          memory = "512Mi"
        }
      }

      env {
        name  = "GF_SECURITY_ADMIN_USER"
        value = "admin"
      }
      env {
        name = "GF_SECURITY_ADMIN_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.grafana_password[0].secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "GF_USERS_ALLOW_SIGN_UP"
        value = "false"
      }
      env {
        name  = "GF_SERVER_ROOT_URL"
        value = "%(protocol)s://%(domain)s/"
      }

      ports {
        container_port = 3000
        name           = "http1"
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_version.grafana_password,
  ]
}

# ═══════════════════════════════════════════════════════════════════════════════
# Cloud Monitoring — Alerting policies
# ═══════════════════════════════════════════════════════════════════════════════

resource "google_monitoring_notification_channel" "email" {
  count        = var.alert_email != "" ? 1 : 0
  display_name = "RAG Alert Email"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
}

resource "google_monitoring_alert_policy" "high_latency" {
  display_name = "[${upper(var.environment)}] RAG High Query Latency"
  combiner     = "OR"

  conditions {
    display_name = "P95 query latency > 15s"
    condition_prometheus_query_language {
      query               = "histogram_quantile(0.95, rate(rag_query_duration_seconds_bucket[5m])) > 15"
      duration            = "300s"
      evaluation_interval = "60s"
    }
  }

  notification_channels = var.alert_email != "" ? [google_monitoring_notification_channel.email[0].name] : []
  depends_on            = [google_project_service.apis]
}

resource "google_monitoring_alert_policy" "error_rate" {
  display_name = "[${upper(var.environment)}] RAG High Error Rate"
  combiner     = "OR"

  conditions {
    display_name = "Query error rate > 10%"
    condition_prometheus_query_language {
      query               = "rate(rag_query_requests_total{status='failure'}[5m]) / rate(rag_query_requests_total[5m]) > 0.1"
      duration            = "300s"
      evaluation_interval = "60s"
    }
  }

  notification_channels = var.alert_email != "" ? [google_monitoring_notification_channel.email[0].name] : []
  depends_on            = [google_project_service.apis]
}
