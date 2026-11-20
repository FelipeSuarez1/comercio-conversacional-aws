output "vpc_id" {
  description = "ID da VPC."
  value       = aws_vpc.principal.id
}

output "subnets_publicas" {
  description = "IDs das 2 sub-redes públicas (ALB, NAT)."
  value       = aws_subnet.publica[*].id
}

output "subnets_privadas" {
  description = "IDs das 2 sub-redes privadas (instâncias ECS)."
  value       = aws_subnet.privada[*].id
  # Com um único apply, as EC2 só sobem depois da rota para o NAT (sem ela não entram no cluster)
  depends_on = [aws_route.privada_nat, aws_route_table_association.privada]
}

output "sg_alb_id" {
  description = "ID do security group do ALB."
  value       = aws_security_group.alb.id
}

output "sg_ecs_id" {
  description = "ID do security group das instâncias ECS."
  value       = aws_security_group.ecs.id
}
