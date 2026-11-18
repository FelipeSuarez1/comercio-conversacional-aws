variable "prefixo" {
  description = "Prefixo dos nomes dos recursos"
  type        = string
}

variable "subnets_privadas" {
  description = "Sub-redes privadas onde o ASG coloca as instâncias"
  type        = list(string)
}

variable "sg_ecs_id" {
  description = "Security group das instâncias ECS"
  type        = string
}

variable "tipo_instancia" {
  description = "Tipo das instâncias EC2 do cluster"
  type        = string
  default     = "t3.small"
}

variable "asg_min" {
  description = "Mínimo de instâncias no ASG"
  type        = number
  default     = 2
}

variable "asg_max" {
  description = "Máximo de instâncias no ASG"
  type        = number
  default     = 4
}

variable "asg_desejado" {
  description = "Capacidade desejada inicial do ASG"
  type        = number
  default     = 2
}

variable "segredo_arn" {
  description = "ARN do segredo do LLM que a role de execução pode ler"
  type        = string
}
