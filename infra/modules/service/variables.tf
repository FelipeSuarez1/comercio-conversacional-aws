variable "prefixo" {
  description = "Prefixo dos nomes de todos os recursos"
  type        = string
}

variable "nome" {
  description = "Nome curto do serviço (ex.: chat-api, order-worker); também é o nome do container"
  type        = string
}

variable "regiao" {
  description = "Região AWS (usada no driver awslogs)"
  type        = string
}

variable "cluster_nome" {
  description = "Nome do cluster ECS"
  type        = string
}

variable "cluster_arn" {
  description = "ARN do cluster ECS"
  type        = string
}

variable "capacity_provider_nome" {
  description = "Capacity Provider usado pelo serviço"
  type        = string
}

variable "execution_role_arn" {
  description = "Role de execução das tasks (ECR, logs, segredo)"
  type        = string
}

variable "imagem" {
  description = "Imagem completa do container (repositorio:tag)"
  type        = string
}

variable "cpu" {
  description = "Unidades de CPU reservadas para o container"
  type        = number
}

variable "memoria_reserva" {
  description = "memoryReservation do container (MiB), usada no posicionamento"
  type        = number
}

variable "memoria_limite" {
  description = "memory do container (MiB), limite rígido"
  type        = number
}

variable "ambiente" {
  description = "Variáveis de ambiente do container (nome -> valor)"
  type        = map(string)
  default     = {}
}

variable "segredos" {
  description = "Variáveis vindas do Secrets Manager (nome da env -> ARN do segredo)"
  type        = map(string)
  default     = {}
}

variable "politica_task_json" {
  description = "JSON da política inline da task role"
  type        = string
}

variable "porta_container" {
  description = "Porta do container exposta ao ALB (null = sem portMappings)"
  type        = number
  default     = null
}

variable "target_group_arn" {
  description = "Target group do ALB (null = serviço sem load balancer)"
  type        = string
  default     = null
}

variable "health_check_comando" {
  description = "Comando do healthCheck do container (ex.: [\"CMD\", \"python\", \"healthcheck.py\"]); null = sem healthCheck"
  type        = list(string)
  default     = null
}

variable "desejado" {
  description = "Número inicial de tasks (depois quem manda é o auto scaling)"
  type        = number
}

variable "minimo" {
  description = "Mínimo de tasks no auto scaling"
  type        = number
}

variable "maximo" {
  description = "Máximo de tasks no auto scaling"
  type        = number
}

variable "escala_cpu_alvo" {
  description = "Alvo de CPU média (%) do target tracking; null = sem política de CPU"
  type        = number
  default     = null
}

variable "escala_metrica_customizada" {
  description = <<-EOT
    Target tracking com métrica calculada; null = sem essa política. Formato:
    { alvo = number, metricas = list(object({ id, expressao (opcional), namespace, nome_metrica,
      dimensoes = map(string), estatistica, retorna = bool, rotulo })) }
    Itens com expressao viram expression; os demais viram metric_stat.
  EOT
  type        = any
  default     = null
}

variable "retencao_logs" {
  description = "Retenção do log group, em dias"
  type        = number
  default     = 7
}
