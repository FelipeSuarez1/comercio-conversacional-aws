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
  # As EC2 dependem do caminho de saída inteiro (rota privada -> NAT -> rota pública -> IGW).
  # No apply, só sobem depois dele (sem saída não entram no cluster). No destroy, a ordem
  # inverte: serviços, Capacity Provider e ASG somem antes das rotas. Sem a parte pública
  # aqui, o destroy apagava a rota do IGW cedo, os agentes ECS perdiam a conexão e os
  # serviços ficavam presos em DRAINING.
  depends_on = [
    aws_route.privada_nat,
    aws_route_table_association.privada,
    aws_route.publica_internet,
    aws_route_table_association.publica,
  ]
}

output "sg_alb_id" {
  description = "ID do security group do ALB."
  value       = aws_security_group.alb.id
}

output "sg_ecs_id" {
  description = "ID do security group das instâncias ECS."
  value       = aws_security_group.ecs.id
}
