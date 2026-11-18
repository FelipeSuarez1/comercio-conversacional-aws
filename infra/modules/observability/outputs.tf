output "topico_arn" {
  description = "ARN do tópico SNS de alertas"
  value       = aws_sns_topic.alertas.arn
}
