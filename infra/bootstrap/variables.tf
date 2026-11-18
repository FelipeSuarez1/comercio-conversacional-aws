variable "regiao" {
  description = "Região AWS onde o bucket do state é criado."
  type        = string
  default     = "sa-east-1"
}

variable "prefixo" {
  description = "Prefixo dos nomes dos recursos."
  type        = string
  default     = "cafe"
}
