# State remoto no bucket criado por infra/bootstrap.
# bucket e region vêm de backend.hcl (fora do git):
#   terraform init -backend-config=backend.hcl
terraform {
  backend "s3" {
    key          = "sa-east-1/terraform.tfstate"
    use_lockfile = true # trava nativa do S3 (sem tabela DynamoDB)
    encrypt      = true
  }
}
