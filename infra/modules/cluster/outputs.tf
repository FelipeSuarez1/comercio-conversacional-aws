output "cluster_nome" {
  description = "Nome do cluster ECS"
  value       = aws_ecs_cluster.this.name
}

output "cluster_arn" {
  description = "ARN do cluster ECS"
  value       = aws_ecs_cluster.this.arn
}

output "capacity_provider_nome" {
  description = "Nome do Capacity Provider (já associado ao cluster)"
  # Vem da associação: serviços que usam o CP esperam ela existir (e somem antes dela)
  value = one(aws_ecs_cluster_capacity_providers.this.capacity_providers)
}

output "execution_role_arn" {
  description = "ARN da role de execução das tasks"
  value       = aws_iam_role.execucao.arn
  # Garante a política (ECR, logs, segredo) antes de uma task tentar usá-la
  depends_on = [aws_iam_role_policy.execucao]
}

output "ecr_chat_api_url" {
  description = "URL do repositório ECR do chat-api"
  value       = aws_ecr_repository.repo["chat-api"].repository_url
}

output "ecr_order_worker_url" {
  description = "URL do repositório ECR do order-worker"
  value       = aws_ecr_repository.repo["order-worker"].repository_url
}

output "asg_nome" {
  description = "Nome do Auto Scaling Group das instâncias"
  value       = aws_autoscaling_group.ecs.name
}
