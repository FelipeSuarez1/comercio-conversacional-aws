variable "repositorios" {
  description = "Imagens a construir: nome do diretório em app/ -> URL do repositório ECR (sem tag)"
  type        = map(string)
}

variable "diretorio_app" {
  description = "Diretório que contém um subdiretório (contexto do build) por imagem"
  type        = string
}

variable "plataforma" {
  description = "Plataforma das imagens (as instâncias do cluster são x86_64)"
  type        = string
  default     = "linux/amd64"
}
