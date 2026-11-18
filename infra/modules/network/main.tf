# Passo 1 — Rede: VPC em 2 AZs, públicas (ALB, NAT) e privadas (instâncias ECS)

# 2 AZs disponíveis na região (nada de nome fixo)
data "aws_availability_zones" "disponiveis" {
  state = "available"

  filter {
    name   = "zone-type"
    values = ["availability-zone"]
  }
}

data "aws_region" "atual" {}

locals {
  azs = slice(data.aws_availability_zones.disponiveis.names, 0, 2)
}

resource "aws_vpc" "principal" {
  cidr_block           = var.cidr_vpc
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.prefixo}-vpc"
  }
}

resource "aws_subnet" "publica" {
  count = 2

  vpc_id                  = aws_vpc.principal.id
  cidr_block              = cidrsubnet(var.cidr_vpc, 8, count.index)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.prefixo}-publica-${count.index + 1}"
  }
}

resource "aws_subnet" "privada" {
  count = 2

  vpc_id            = aws_vpc.principal.id
  cidr_block        = cidrsubnet(var.cidr_vpc, 8, 10 + count.index)
  availability_zone = local.azs[count.index]

  tags = {
    Name = "${var.prefixo}-privada-${count.index + 1}"
  }
}

# Internet Gateway: porta de entrada/saída das sub-redes públicas
resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.principal.id

  tags = {
    Name = "${var.prefixo}-igw"
  }
}

# NAT Gateway (1 só, na pública da 1a AZ) com IP elástico
resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name = "${var.prefixo}-nat-eip"
  }

  depends_on = [aws_internet_gateway.igw]
}

resource "aws_nat_gateway" "nat" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.publica[0].id

  tags = {
    Name = "${var.prefixo}-nat"
  }

  depends_on = [aws_internet_gateway.igw]
}

# Tabela de rotas pública: 0.0.0.0/0 -> IGW
resource "aws_route_table" "publica" {
  vpc_id = aws_vpc.principal.id

  tags = {
    Name = "${var.prefixo}-rt-publica"
  }
}

resource "aws_route" "publica_internet" {
  route_table_id         = aws_route_table.publica.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.igw.id
}

resource "aws_route_table_association" "publica" {
  count = 2

  subnet_id      = aws_subnet.publica[count.index].id
  route_table_id = aws_route_table.publica.id
}

# Tabela de rotas privada (uma para as duas AZs, já que há um único NAT): 0.0.0.0/0 -> NAT
resource "aws_route_table" "privada" {
  vpc_id = aws_vpc.principal.id

  tags = {
    Name = "${var.prefixo}-rt-privada"
  }
}

resource "aws_route" "privada_nat" {
  route_table_id         = aws_route_table.privada.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.nat.id
}

resource "aws_route_table_association" "privada" {
  count = 2

  subnet_id      = aws_subnet.privada[count.index].id
  route_table_id = aws_route_table.privada.id
}

# Endpoints Gateway (gratuitos) na tabela privada: tiram S3 (camadas do ECR) e DynamoDB do NAT
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.principal.id
  service_name      = "com.amazonaws.${data.aws_region.atual.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.privada.id]

  tags = {
    Name = "${var.prefixo}-vpce-s3"
  }
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.principal.id
  service_name      = "com.amazonaws.${data.aws_region.atual.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.privada.id]

  tags = {
    Name = "${var.prefixo}-vpce-dynamodb"
  }
}

# Passo 2 — Security groups
# O Terraform remove a saída padrão (tudo liberado) ao criar o SG; as regras
# ficam em recursos separados para evitar ciclo entre os dois SGs.
# Descrições de SG só aceitam ASCII (sem acentos).

resource "aws_security_group" "alb" {
  name        = "${var.prefixo}-alb-sg"
  description = "ALB: HTTP 80 da internet"
  vpc_id      = aws_vpc.principal.id

  tags = {
    Name = "${var.prefixo}-alb-sg"
  }
}

resource "aws_security_group" "ecs" {
  name        = "${var.prefixo}-ecs-sg"
  description = "Instancias ECS: portas dinamicas somente a partir do ALB"
  vpc_id      = aws_vpc.principal.id

  tags = {
    Name = "${var.prefixo}-ecs-sg"
  }
}

# alb-sg: entra 80 da internet; sai só para as portas dinâmicas das instâncias
resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP da internet"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "alb_para_ecs" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Portas dinamicas das instancias ECS"
  ip_protocol                  = "tcp"
  from_port                    = 32768
  to_port                      = 65535
  referenced_security_group_id = aws_security_group.ecs.id
}

# ecs-sg: entra só do ALB; sai só HTTPS (ECR, ECS, SSM, SQS, CloudWatch, LLM)
resource "aws_vpc_security_group_ingress_rule" "ecs_do_alb" {
  security_group_id            = aws_security_group.ecs.id
  description                  = "Portas dinamicas somente a partir do ALB"
  ip_protocol                  = "tcp"
  from_port                    = 32768
  to_port                      = 65535
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_egress_rule" "ecs_https" {
  security_group_id = aws_security_group.ecs.id
  description       = "HTTPS de saida"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}
