provider "aws" {
  region = var.regiao

  default_tags {
    tags = {
      Projeto = var.prefixo
      Etapa   = "terraform"
    }
  }
}

# Token de login no ECR da conta/região atual. Ephemeral: é pedido de novo a cada
# plan/apply e não fica gravado no state (um data source guardaria a senha lá).
ephemeral "aws_ecr_authorization_token" "this" {}

locals {
  # No Windows (caminho tipo "C:/...") o Docker Desktop escuta num named pipe;
  # nos outros sistemas, null = DOCKER_HOST ou o socket padrão.
  windows     = can(regex("^[A-Za-z]:", abspath(path.root)))
  docker_host = var.docker_host != null ? var.docker_host : (local.windows ? "npipe:////./pipe/docker_engine" : null)
}

# Build local e push para o ECR (módulo images)
provider "docker" {
  host = local.docker_host

  registry_auth {
    address  = ephemeral.aws_ecr_authorization_token.this.proxy_endpoint
    username = ephemeral.aws_ecr_authorization_token.this.user_name
    password = ephemeral.aws_ecr_authorization_token.this.password
  }
}
