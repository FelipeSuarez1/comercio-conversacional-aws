variable "prefixo" {
  description = "Prefixo dos nomes dos recursos"
  type        = string
}

variable "llm_modo" {
  description = "Modo do LLM (real ou fake); no fake o segredo recebe um placeholder"
  type        = string
}

variable "llm_api_key" {
  description = "Chave da API do LLM (usada só no modo real). Write-only: não vai para o state"
  type        = string
  default     = null
  sensitive   = true
  ephemeral   = true
}

variable "llm_api_key_versao" {
  description = "Versão do valor do segredo; incremente para regravar a chave"
  type        = number
  default     = 1
}
