variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for all resources"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Deployment environment: staging | production"
  type        = string
  default     = "production"
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be 'staging' or 'production'."
  }
}

variable "app_name" {
  description = "Application name used for resource naming"
  type        = string
  default     = "rag-on-gcp"
}

# ── Container Image ─────────────────────────────────────────────────────────
variable "image_tag" {
  description = "Docker image tag to deploy (e.g. 'latest' or a specific SHA)"
  type        = string
  default     = "latest"
}

# ── Cloud Run ────────────────────────────────────────────────────────────────
variable "cloud_run_min_instances" {
  description = "Minimum Cloud Run instances (0 = scale to zero; 2+ for always-on)"
  type        = number
  default     = 2
}

variable "cloud_run_max_instances" {
  description = "Maximum Cloud Run instances"
  type        = number
  default     = 10
}

variable "cloud_run_cpu" {
  description = "CPU allocation per instance (1000m = 1 vCPU)"
  type        = string
  default     = "2000m"
}

variable "cloud_run_memory" {
  description = "Memory per instance"
  type        = string
  default     = "4Gi"
}

variable "cloud_run_concurrency" {
  description = "Max concurrent requests per instance"
  type        = number
  default     = 25
}

variable "cloud_run_timeout" {
  description = "Request timeout in seconds (max 3600 for Cloud Run)"
  type        = number
  default     = 300
}

# ── Vertex AI ────────────────────────────────────────────────────────────────
variable "vertex_ai_location" {
  description = "Vertex AI region"
  type        = string
  default     = "us-central1"
}

variable "embedding_model" {
  description = "Vertex AI text embedding model"
  type        = string
  default     = "text-embedding-004"
}

variable "llm_model" {
  description = "Vertex AI generative model"
  type        = string
  default     = "gemini-1.5-pro-002"
}

# ── Storage ──────────────────────────────────────────────────────────────────
variable "gcs_location" {
  description = "GCS bucket location"
  type        = string
  default     = "US"
}

variable "gcs_storage_class" {
  description = "GCS storage class"
  type        = string
  default     = "STANDARD"
}

# ── Redis (Memorystore) ───────────────────────────────────────────────────────
variable "enable_redis" {
  description = "Enable Cloud Memorystore Redis for query caching"
  type        = bool
  default     = true
}

variable "redis_memory_size_gb" {
  description = "Redis memory size in GB"
  type        = number
  default     = 1
}

# ── Networking ────────────────────────────────────────────────────────────────
variable "vpc_connector_cidr" {
  description = "CIDR range for the Serverless VPC Access connector"
  type        = string
  default     = "10.8.0.0/28"
}

# ── Monitoring ───────────────────────────────────────────────────────────────
variable "enable_grafana" {
  description = "Deploy Grafana as a Cloud Run service"
  type        = bool
  default     = true
}

variable "grafana_password" {
  description = "Grafana admin password (stored in Secret Manager)"
  type        = string
  sensitive   = true
  default     = "ChangeMe123!"
}

variable "alert_email" {
  description = "Email address for Cloud Monitoring alerts"
  type        = string
  default     = ""
}
