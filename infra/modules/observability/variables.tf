variable "prefixo" {
  description = "Prefixo dos nomes dos recursos"
  type        = string
}

variable "cluster_nome" {
  description = "Nome do cluster ECS"
  type        = string
}

variable "servicos" {
  description = "Nomes completos dos serviços ECS (ex.: cafe-chat-api)"
  type        = list(string)
}

variable "asg_nome" {
  description = "Nome do Auto Scaling Group das instâncias do cluster"
  type        = string
}

variable "asg_min" {
  description = "Mínimo de instâncias do ASG (limiar do alarme de instâncias em serviço)"
  type        = number
}

variable "alb_arn_suffix" {
  description = "Sufixo do ARN do ALB (dimensão LoadBalancer)"
  type        = string
}

variable "target_group_arn_suffix" {
  description = "Sufixo do ARN do target group (dimensão TargetGroup)"
  type        = string
}

variable "fila_nome" {
  description = "Nome da fila de pedidos"
  type        = string
}

variable "dlq_nome" {
  description = "Nome da DLQ de pedidos"
  type        = string
}

variable "log_groups" {
  description = "Log groups da aplicação que recebem o metric filter de ERROR"
  type        = list(string)
}
