output "topico_arn" {
  description = "ARN do tópico SNS de alertas"
  value       = aws_sns_topic.alertas.arn
}

output "alarmes" {
  description = "Nomes dos alarmes do CloudWatch"
  value = sort(concat(
    [for a in aws_cloudwatch_metric_alarm.tasks_abaixo : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.cluster_reserva : a.alarm_name],
    [
      aws_cloudwatch_metric_alarm.asg_instancias_abaixo.alarm_name,
      aws_cloudwatch_metric_alarm.alb_5xx.alarm_name,
      aws_cloudwatch_metric_alarm.tg_hosts_nao_saudaveis.alarm_name,
      aws_cloudwatch_metric_alarm.fila_mensagem_antiga.alarm_name,
      aws_cloudwatch_metric_alarm.dlq_com_mensagens.alarm_name,
      aws_cloudwatch_metric_alarm.erros_no_log.alarm_name,
    ]
  ))
}
