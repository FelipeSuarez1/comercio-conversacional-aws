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

variable "docker_host" {
  description = "Endereço do Docker usado no build. null = automático (named pipe do Docker Desktop no Windows; DOCKER_HOST ou socket padrão nos outros)."
  type        = string
  default     = null
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

variable "llm_api_key" {
  description = "Chave do LLM (modo real). Passe só por TF_VAR_llm_api_key, nunca em arquivo; write-only, não vai para o state."
  type        = string
  default     = null
  sensitive   = true
  ephemeral   = true
}

variable "llm_api_key_versao" {
  description = "Incremente para regravar o segredo (troca de chave). Trocar llm_modo já regrava."
  type        = number
  default     = 1
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

# ---------------------------------------------------------------- Escala das tasks

variable "chat_api_cpu_alvo" {
  description = "Alvo de CPU média (%) do target tracking do chat-api."
  type        = number
  default     = 60
}

variable "chat_api_requisicoes_por_task" {
  description = "Alvo de requisições por task por minuto (ALBRequestCountPerTarget) do chat-api."
  type        = number
  default     = 600
}

variable "worker_backlog_por_task" {
  description = "Alvo de mensagens visíveis na fila por task do order-worker."
  type        = number
  default     = 20
}

variable "worker_cooldown_saida" {
  description = "Cooldown de scale-out do order-worker (s)."
  type        = number
  default     = 30
}

variable "worker_cooldown_entrada" {
  description = "Cooldown de scale-in do order-worker (s); mais lento que o de saída."
  type        = number
  default     = 120
}

# ---------------------------------------------------------------- Alertas

variable "email_alertas" {
  description = "E-mail assinado no tópico SNS de alertas. Vazio = sem assinatura. A AWS manda um e-mail de confirmação."
  type        = string
  default     = ""

  validation {
    condition     = var.email_alertas == "" || can(regex("^[^@ ]+@[^@ ]+[.][^@ ]+$", var.email_alertas))
    error_message = "email_alertas deve ser vazio ou um endereço de e-mail."
  }
}
