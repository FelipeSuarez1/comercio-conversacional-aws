# Observabilidade: tópico SNS e alarmes do passo 12 de Ohio.

locals {
  acoes = [aws_sns_topic.alertas.arn]

  # Namespace da métrica de erros nos logs ("Cafe" com o prefixo padrão)
  namespace_logs = title(var.prefixo)

  # Log group "/ecs/<prefixo>/<servico>" -> nome curto do serviço
  log_groups = { for lg in var.log_groups : lg => element(split("/", lg), length(split("/", lg)) - 1) }
}

# Tópico de alertas (assinatura de e-mail é feita fora do Terraform)
resource "aws_sns_topic" "alertas" {
  name = "${var.prefixo}-alertas"
}

# Tasks abaixo do desejado: DesiredTaskCount - RunningTaskCount (Container Insights), um por serviço
resource "aws_cloudwatch_metric_alarm" "tasks_abaixo" {
  for_each = toset(var.servicos)

  alarm_name          = "${each.value}-tasks-abaixo"
  alarm_description   = "Servico ${trimprefix(each.value, "${var.prefixo}-")} com menos tasks rodando que o desejado"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.acoes

  metric_query {
    id          = "rodando"
    return_data = false

    metric {
      namespace   = "ECS/ContainerInsights"
      metric_name = "RunningTaskCount"
      period      = 60
      stat        = "Average"
      dimensions = {
        ClusterName = var.cluster_nome
        ServiceName = each.value
      }
    }
  }

  metric_query {
    id          = "desejado"
    return_data = false

    metric {
      namespace   = "ECS/ContainerInsights"
      metric_name = "DesiredTaskCount"
      period      = 60
      stat        = "Average"
      dimensions = {
        ClusterName = var.cluster_nome
        ServiceName = each.value
      }
    }
  }

  metric_query {
    id          = "faltando"
    expression  = "desejado - rodando"
    label       = "Tasks abaixo do desejado"
    return_data = true
  }
}

# Reserva de CPU e de memória do cluster > 85%
resource "aws_cloudwatch_metric_alarm" "cluster_reserva" {
  for_each = toset(["CPUReservation", "MemoryReservation"])

  alarm_name          = "${var.prefixo}-cluster-${each.value}-alta"
  alarm_description   = "${each.value} do cluster acima de 85%"
  namespace           = "AWS/ECS"
  metric_name         = each.value
  dimensions          = { ClusterName = var.cluster_nome }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 5
  comparison_operator = "GreaterThanThreshold"
  threshold           = 85
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.acoes
}

# Instâncias InService abaixo do mínimo do ASG
resource "aws_cloudwatch_metric_alarm" "asg_instancias_abaixo" {
  alarm_name          = "${var.prefixo}-asg-instancias-abaixo"
  alarm_description   = "Menos de ${var.asg_min} instancias InService no ASG"
  namespace           = "AWS/AutoScaling"
  metric_name         = "GroupInServiceInstances"
  dimensions          = { AutoScalingGroupName = var.asg_nome }
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 2
  comparison_operator = "LessThanThreshold"
  threshold           = var.asg_min
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.acoes
}

# ALB: 5XX vindos das tasks
resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${var.prefixo}-alb-5xx"
  alarm_description   = "5 ou mais respostas 5XX das tasks em 1 minuto"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { LoadBalancer = var.alb_arn_suffix }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.acoes
}

# Target group: alvos não saudáveis
resource "aws_cloudwatch_metric_alarm" "tg_hosts_nao_saudaveis" {
  alarm_name        = "${var.prefixo}-tg-hosts-nao-saudaveis"
  alarm_description = "Algum alvo do chat-api falhando no /health"
  namespace         = "AWS/ApplicationELB"
  metric_name       = "UnHealthyHostCount"
  dimensions = {
    TargetGroup  = var.target_group_arn_suffix
    LoadBalancer = var.alb_arn_suffix
  }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.acoes
}

# Fila: mensagem mais antiga com mais de 5 minutos
resource "aws_cloudwatch_metric_alarm" "fila_mensagem_antiga" {
  alarm_name          = "${var.prefixo}-fila-mensagem-antiga"
  alarm_description   = "Pedido esperando ha mais de 5 minutos na fila"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = var.fila_nome }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 300
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.acoes
}

# DLQ com mensagens
resource "aws_cloudwatch_metric_alarm" "dlq_com_mensagens" {
  alarm_name          = "${var.prefixo}-dlq-com-mensagens"
  alarm_description   = "Mensagem caiu na DLQ de pedidos"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = var.dlq_nome }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.acoes
}

# Metric filter: conta linhas com ERROR em cada log group da aplicação
resource "aws_cloudwatch_log_metric_filter" "erros" {
  for_each = local.log_groups

  name           = "${var.prefixo}-${each.value}-erros"
  log_group_name = each.key
  pattern        = "ERROR"

  metric_transformation {
    name          = "ErrosNoLog"
    namespace     = local.namespace_logs
    value         = "1"
    default_value = "0"
  }
}

# Erros nos logs: soma da métrica dos metric filters
resource "aws_cloudwatch_metric_alarm" "erros_no_log" {
  alarm_name          = "${var.prefixo}-erros-no-log"
  alarm_description   = "Linha com ERROR nos logs do chat-api ou do order-worker"
  namespace           = local.namespace_logs
  metric_name         = "ErrosNoLog"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.acoes

  depends_on = [aws_cloudwatch_log_metric_filter.erros]
}
