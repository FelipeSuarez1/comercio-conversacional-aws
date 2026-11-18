provider "aws" {
  region = var.regiao

  default_tags {
    tags = {
      Projeto = var.prefixo
      Etapa   = "terraform"
    }
  }
}
