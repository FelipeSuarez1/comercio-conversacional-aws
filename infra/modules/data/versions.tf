terraform {
  required_version = ">= 1.11" # atributos write-only (secret_string_wo)

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
