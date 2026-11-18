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
  description = "ARN do segredo (recipiente sem valor)"
  value       = aws_secretsmanager_secret.llm_api_key.arn
}
