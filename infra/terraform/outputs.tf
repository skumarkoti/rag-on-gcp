output "rag_app_url" {
  description = "Public URL of the RAG application"
  value       = google_cloud_run_v2_service.rag_app.uri
}

output "grafana_url" {
  description = "Public URL of the Grafana dashboard"
  value       = var.enable_grafana ? google_cloud_run_v2_service.grafana[0].uri : "Grafana not deployed"
}

output "gcs_bucket_name" {
  description = "GCS bucket name for PDFs and ChromaDB"
  value       = google_storage_bucket.rag_bucket.name
}

output "artifact_registry_repo" {
  description = "Artifact Registry repository for Docker images"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${var.app_name}"
}

output "image_uri" {
  description = "Full Docker image URI to use in deployments"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${var.app_name}/${var.app_name}:${var.image_tag}"
}

output "service_account_email" {
  description = "Service account email used by the RAG application"
  value       = google_service_account.rag_sa.email
}

output "redis_host" {
  description = "Redis host (only available within VPC)"
  value       = var.enable_redis ? google_redis_instance.rag_cache[0].host : "Redis not enabled"
}

output "vpc_connector_name" {
  description = "Serverless VPC Access connector name"
  value       = google_vpc_access_connector.rag_connector.name
}
