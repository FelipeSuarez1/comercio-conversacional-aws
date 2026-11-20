output "tabela_produtos_nome" {
  value = aws_dynamodb_table.produtos.name
}

output "tabela_pedidos_nome" {
  value = aws_dynamodb_table.pedidos.name
}

output "tabela_conversas_nome" {
  value = aws_dynamodb_table.conversas.name
}

output "tabela_produtos_arn" {
  value = aws_dynamodb_table.produtos.arn
}

output "tabela_pedidos_arn" {
  value = aws_dynamodb_table.pedidos.arn
}

output "tabela_conversas_arn" {
  value = aws_dynamodb_table.conversas.arn
}

output "fila_url" {
  value = aws_sqs_queue.pedidos.url
}

output "fila_arn" {
  value = aws_sqs_queue.pedidos.arn
}

output "fila_nome" {
  value = aws_sqs_queue.pedidos.name
}

output "dlq_url" {
  value = aws_sqs_queue.pedidos_dlq.url
}

output "dlq_arn" {
  value = aws_sqs_queue.pedidos_dlq.arn
}

output "dlq_nome" {
  value = aws_sqs_queue.pedidos_dlq.name
}

output "segredo_arn" {
  description = "ARN do segredo da chave do LLM"
  value       = aws_secretsmanager_secret.llm_api_key.arn
  # Quem usa o segredo (task do chat-api) espera ele ter um valor
  depends_on = [aws_secretsmanager_secret_version.llm_api_key]
}

output "catalogo_ids" {
  description = "produto_id dos itens do catálogo criados pelo Terraform"
  value       = sort(keys(aws_dynamodb_table_item.produto))
}
