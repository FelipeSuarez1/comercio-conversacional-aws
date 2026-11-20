# Segredo da chave do LLM
resource "aws_secretsmanager_secret" "llm_api_key" {
  name                    = "${var.prefixo}/llm-api-key"
  description             = "Chave da API do LLM usada pelo chat-api"
  recovery_window_in_days = 0 # apaga na hora, para poder destruir e recriar no mesmo dia
}

locals {
  # Derivados de var.llm_api_key (ephemeral): não vão para o plano nem para o state
  chave_informada = try(trimspace(var.llm_api_key), "") != ""
  valor_segredo   = var.llm_modo == "real" && local.chave_informada ? var.llm_api_key : "modo-fake"
}

# Valor do segredo por atributo write-only: o Terraform envia à AWS e não guarda.
# No modo fake (ou sem chave) grava um placeholder: sem valor a task do chat-api não inicia.
# Só é regravado quando a versão muda: ao trocar llm_modo ou incrementar llm_api_key_versao.
resource "aws_secretsmanager_secret_version" "llm_api_key" {
  secret_id                = aws_secretsmanager_secret.llm_api_key.id
  secret_string_wo         = local.valor_segredo
  secret_string_wo_version = var.llm_api_key_versao * 10 + (var.llm_modo == "real" ? 1 : 0)
}

# Tabelas DynamoDB (chaves conforme docs/contratos.md)
resource "aws_dynamodb_table" "produtos" {
  name         = "${var.prefixo}-produtos"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "produto_id"

  attribute {
    name = "produto_id"
    type = "S"
  }
}

resource "aws_dynamodb_table" "pedidos" {
  name         = "${var.prefixo}-pedidos"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pedido_id"

  attribute {
    name = "pedido_id"
    type = "S"
  }
}

resource "aws_dynamodb_table" "conversas" {
  name         = "${var.prefixo}-conversas"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "conversa_id"
  range_key    = "ts"

  attribute {
    name = "conversa_id"
    type = "S"
  }

  attribute {
    name = "ts"
    type = "S"
  }
}

# DLQ: retenção máxima (14 dias) para dar tempo de investigar
resource "aws_sqs_queue" "pedidos_dlq" {
  name                      = "${var.prefixo}-pedidos-dlq"
  message_retention_seconds = 1209600
}

# Fila de pedidos: visibility 60 s, long polling 20 s, DLQ após 3 recebimentos
resource "aws_sqs_queue" "pedidos" {
  name                       = "${var.prefixo}-pedidos"
  visibility_timeout_seconds = 60
  receive_wait_time_seconds  = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.pedidos_dlq.arn
    maxReceiveCount     = 3
  })
}
