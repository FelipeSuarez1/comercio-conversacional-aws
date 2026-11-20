output "imagens" {
  description = "Imagem já enviada ao ECR (repositorio:tag), por nome. Usar este valor faz o serviço esperar o push."
  value       = { for nome, img in docker_registry_image.this : nome => img.name }
}

output "digests" {
  description = "Digest sha256 de cada imagem no ECR"
  value       = { for nome, img in docker_registry_image.this : nome => img.sha256_digest }
}

output "tags" {
  description = "Tag (hash do código) de cada imagem"
  value       = local.tag
}
