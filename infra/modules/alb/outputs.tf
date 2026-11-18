output "alb_dns" {
  description = "DNS público do ALB"
  value       = aws_lb.this.dns_name
}

output "alb_arn_suffix" {
  description = "Sufixo do ARN do ALB (dimensão LoadBalancer no CloudWatch)"
  value       = aws_lb.this.arn_suffix
}

output "target_group_arn" {
  description = "ARN do target group do chat-api"
  value       = aws_lb_target_group.chat_api.arn
}

output "target_group_arn_suffix" {
  description = "Sufixo do ARN do target group (dimensão TargetGroup no CloudWatch)"
  value       = aws_lb_target_group.chat_api.arn_suffix
}

output "listener_arn" {
  description = "ARN do listener HTTP 80"
  value       = aws_lb_listener.http.arn
}
