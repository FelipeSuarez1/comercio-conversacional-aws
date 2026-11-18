variable "regiao" {
  description = "Região da AWS onde tudo é criado."
  type        = string
  default     = "sa-east-1"
}

variable "prefixo" {
  description = "Prefixo dos nomes de todos os recursos (e valor da tag Projeto)."
  type        = string
  default     = "cafe"
}

variable "cidr_vpc" {
  description = "Bloco CIDR da VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "imagem_tag" {
  description = "Tag das imagens no ECR (hash curto do commit), igual para os dois serviços."
  type        = string
}

variable "llm_modo" {
  description = "Modo do LLM no chat-api: real (chama o provedor) ou fake (respostas simuladas)."
  type        = string
  default     = "fake"

  validation {
    condition     = contains(["real", "fake"], var.llm_modo)
    error_message = "llm_modo deve ser \"real\" ou \"fake\"."
  }
}

variable "llm_base_url" {
  description = "URL base de uma API compatível com o formato OpenAI de chat completions. Obrigatória no modo real."
  type        = string
  default     = ""

  validation {
    condition     = var.llm_modo != "real" || var.llm_base_url != ""
    error_message = "Com llm_modo = \"real\", defina llm_base_url."
  }
}

variable "model_id" {
  description = "Id do modelo no provedor de LLM. Obrigatório no modo real."
  type        = string
  default     = ""

  validation {
    condition     = var.llm_modo != "real" || var.model_id != ""
    error_message = "Com llm_modo = \"real\", defina model_id."
  }
}

variable "log_level" {
  description = "Nível de log dos dois serviços."
  type        = string
  default     = "INFO"
}

variable "tipo_instancia" {
  description = "Tipo das instâncias EC2 do cluster."
  type        = string
  default     = "t3.small"
}

variable "asg_min" {
  description = "Mínimo de instâncias no ASG."
  type        = number
  default     = 2
}

variable "asg_max" {
  description = "Máximo de instâncias no ASG."
  type        = number
  default     = 4
}

variable "asg_desejado" {
  description = "Instâncias desejadas no ASG ao criar (depois quem manda é o capacity provider)."
  type        = number
  default     = 2
}
