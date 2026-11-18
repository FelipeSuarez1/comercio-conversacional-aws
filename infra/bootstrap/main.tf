# Conta atual: entra no nome do bucket (nomes de S3 são globais)
data "aws_caller_identity" "atual" {}

resource "aws_s3_bucket" "tfstate" {
  bucket = "${var.prefixo}-tfstate-${data.aws_caller_identity.atual.account_id}-${var.regiao}"

  # O state não pode sumir por engano
  force_destroy = false

  tags = {
    Name = "${var.prefixo}-tfstate"
  }
}

# Versionamento: permite recuperar versões anteriores do state
resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Criptografia em repouso (SSE-S3)
resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Nada público
resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
