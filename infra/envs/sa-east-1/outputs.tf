output "url_alb" {
  description = "URL pública da aplicação (ALB)."
  value       = "http://${module.alb.alb_dns}"
}

output "ecr_chat_api_url" {
  description = "Repositório ECR do chat-api (sem tag)."
  value       = module.cluster.ecr_chat_api_url
}

output "ecr_order_worker_url" {
  description = "Repositório ECR do order-worker (sem tag)."
  value       = module.cluster.ecr_order_worker_url
}

output "cluster_nome" {
  description = "Nome do cluster ECS."
  value       = module.cluster.cluster_nome
}

output "fila_url" {
  description = "URL da fila de pedidos."
  value       = module.data.fila_url
}

output "imagens" {
  description = "Imagens enviadas ao ECR (repositorio:tag, tag = hash do código)."
  value       = module.images.imagens
}

output "segredo_arn" {
  description = "ARN do segredo da chave do LLM (valor gravado pelo Terraform como write-only)."
  value       = module.data.segredo_arn
}

output "tabela_produtos_nome" {
  description = "Tabela do catálogo (populada pelo Terraform; scripts/seed.py reseta o estoque)."
  value       = module.data.tabela_produtos_nome
}
