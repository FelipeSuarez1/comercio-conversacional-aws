# Segredo da chave do LLM: só o recipiente. O valor é gravado depois pela CLI/console
# e nunca passa pelo Terraform (não vai para o state).
resource "aws_secretsmanager_secret" "llm_api_key" {
  name                    = "${var.prefixo}/llm-api-key"
  description             = "Chave da API do LLM usada pelo chat-api"
  recovery_window_in_days = 0 # apaga na hora, para poder destruir e recriar no mesmo dia
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
