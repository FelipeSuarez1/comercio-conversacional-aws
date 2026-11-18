output "bucket_nome" {
  description = "Nome do bucket do state remoto (vai no backend.hcl de envs/sa-east-1)."
  value       = aws_s3_bucket.tfstate.bucket
}
