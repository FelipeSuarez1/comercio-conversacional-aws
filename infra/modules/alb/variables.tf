variable "prefixo" {
  description = "Prefixo dos nomes dos recursos"
  type        = string
}

variable "vpc_id" {
  description = "VPC do target group"
  type        = string
}

variable "subnets_publicas" {
  description = "Sub-redes públicas onde o ALB fica (2 AZs)"
  type        = list(string)
}

variable "sg_alb_id" {
  description = "Security group do ALB"
  type        = string
}
