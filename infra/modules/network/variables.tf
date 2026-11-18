variable "prefixo" {
  description = "Prefixo dos nomes dos recursos."
  type        = string
}

variable "cidr_vpc" {
  description = "Bloco CIDR da VPC."
  type        = string
  default     = "10.0.0.0/16"
}
