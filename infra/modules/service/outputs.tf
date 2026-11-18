output "servico_nome" {
  description = "Nome do serviço ECS"
  value       = aws_ecs_service.this.name
}

output "task_role_arn" {
  description = "ARN da task role do serviço"
  value       = aws_iam_role.task.arn
}

output "log_group_nome" {
  description = "Nome do log group do serviço"
  value       = aws_cloudwatch_log_group.this.name
}
