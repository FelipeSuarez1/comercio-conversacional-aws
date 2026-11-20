# Observabilidade: tópico SNS e alarmes do passo 12 de Ohio.
# Limiares calibrados com os testes de carga e de falha de docs/evidencias.md
# (justificativa por alarme em docs/terraform.md, seção "Alarmes").

locals {
  acoes = [aws_sns_topic.alertas.arn]

  # Namespace da métrica de erros nos logs ("Cafe" com o prefixo padrão)
  namespace_logs = title(var.prefixo)

  # Log group "/ecs/<prefixo>/<servico>" -> nome curto do serviço
  log_groups = { for lg in var.log_groups : lg => element(split("/", lg), length(split("/", lg)) - 1) }
}

# Tópico de alertas
resource "aws_sns_topic" "alertas" {
  name = "${var.prefixo}-alertas"
}

# Assinatura de e-mail opcional: a AWS manda um e-mail de confirmação e a assinatura
# fica "PendingConfirmation" até o link ser clicado.
resource "aws_sns_topic_subscription" "email" {
  count = var.email_alertas == "" ? 0 : 1

  topic_arn = aws_sns_topic.alertas.arn
  protocol  = "email"
  endpoint  = var.email_alertas
}

# Tasks abaixo do desejado: DesiredTaskCount - RunningTaskCount (Container Insights), um por serviço.
# 5 min: no teste de carga, tasks novas ficaram até ~3 min pendentes (download da
# imagem, espera por EC2 nova) e a reposição de task/instância levou 1 a 1,5 min.
resource "aws_cloudwatch_metric_alarm" "tasks_abaixo" {
  for_each = toset(var.servicos)

  alarm_name          = "${each.value}-tasks-abaixo"
  alarm_description   = "Servico ${trimprefix(each.value, "${var.prefixo}-")} com menos tasks rodando que o desejado por 5 min"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 5
  datapoints_to_alarm = 5
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

# Reserva de CPU e de memória do cluster > 85% por 5 min. No teste de carga a reserva
# de memória chegou ao teto por ~3 min até o Capacity Provider subir EC2 nova; 5 min
# acima de 85% indica que ele não conseguiu (ASG no máximo ou falha ao subir instância).
resource "aws_cloudwatch_metric_alarm" "cluster_reserva" {
  for_each = toset(["CPUReservation", "MemoryReservation"])

  alarm_name          = "${var.prefixo}-cluster-${each.value}-alta"
  alarm_description   = "${each.value} do cluster acima de 85% por 5 min"
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

# Instâncias InService abaixo do mínimo do ASG por 3 min: a reposição de uma EC2
# terminada levou 1 a 1,5 min nos testes; acima disso o ASG não está conseguindo repor.
resource "aws_cloudwatch_metric_alarm" "asg_instancias_abaixo" {
  alarm_name          = "${var.prefixo}-asg-instancias-abaixo"
  alarm_description   = "Menos de ${var.asg_min} instancias InService no ASG por 3 min"
  namespace           = "AWS/AutoScaling"
  metric_name         = "GroupInServiceInstances"
  dimensions          = { AutoScalingGroupName = var.asg_nome }
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 3
  comparison_operator = "LessThanThreshold"
  threshold           = var.asg_min
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.acoes
}

# ALB: taxa de 5XX (das tasks + do próprio ALB) acima de 1% por 2 min seguidos.
# No teste de carga saturando o chat (CPU até 337%) a taxa de erro foi 0,04%
# (38 em 103 969); 1% fica bem acima disso e pega task quebrada ou sem alvo saudável.
# Com menos de 20 requisições no minuto a taxa vale 0 (um erro isolado não alarma).
# Os 503 do ALB sem alvo não entram no RequestCount, por isso somam no total.
resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${var.prefixo}-alb-5xx"
  alarm_description   = "Mais de 1% das respostas do ALB com 5XX por 2 min"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 1
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.acoes

  dynamic "metric_query" {
    for_each = {
      requisicoes = "RequestCount"
      erros_task  = "HTTPCode_Target_5XX_Count"
      erros_alb   = "HTTPCode_ELB_5XX_Count"
    }

    content {
      id          = metric_query.key
      return_data = false

      metric {
        namespace   = "AWS/ApplicationELB"
        metric_name = metric_query.value
        period      = 60
        stat        = "Sum"
        dimensions  = { LoadBalancer = var.alb_arn_suffix }
      }
    }
  }

  metric_query {
    id          = "total"
    expression  = "FILL(requisicoes, 0) + FILL(erros_alb, 0)"
    return_data = false
  }

  metric_query {
    id          = "taxa_5xx"
    expression  = "IF(total >= 20, 100 * (FILL(erros_task, 0) + FILL(erros_alb, 0)) / total, 0)"
    label       = "Respostas 5XX (%)"
    return_data = true
  }
}

# Target group: alvo não saudável por 3 min. Com task parada ou EC2 perdida o alvo
# saiu e foi reposto em ~1 min nos testes; 3 min indica alvo preso falhando no /health.
resource "aws_cloudwatch_metric_alarm" "tg_hosts_nao_saudaveis" {
  alarm_name        = "${var.prefixo}-tg-hosts-nao-saudaveis"
  alarm_description = "Algum alvo do chat-api falhando no /health por 3 min"
  namespace         = "AWS/ApplicationELB"
  metric_name       = "UnHealthyHostCount"
  dimensions = {
    TargetGroup  = var.target_group_arn_suffix
    LoadBalancer = var.alb_arn_suffix
  }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.acoes
}

# Fila: mensagem mais antiga com mais de 10 min, por 2 min. Uma rajada de 6000 pedidos
# foi esvaziada por um único worker em ~5 min (1300 a 1800 por minuto); o dobro disso
# significa worker parado, falhando ou no máximo de tasks.
resource "aws_cloudwatch_metric_alarm" "fila_mensagem_antiga" {
  alarm_name          = "${var.prefixo}-fila-mensagem-antiga"
  alarm_description   = "Pedido esperando ha mais de 10 minutos na fila"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = var.fila_nome }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  comparison_operator = "GreaterThanThreshold"
  threshold           = 600
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.acoes
}

# DLQ com mensagens: qualquer pedido que falhou 3 vezes precisa de análise
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

# Metric filter: conta linhas com ERROR ou CRITICAL em cada log group da aplicação.
# Padrão de termos (não de JSON): casa com qualquer linha que contenha o termo, então
# serve tanto para o log em texto quanto para JSON ("level":"ERROR" ou "nivel":"ERROR").
resource "aws_cloudwatch_log_metric_filter" "erros" {
  for_each = local.log_groups

  name           = "${var.prefixo}-${each.value}-erros"
  log_group_name = each.key
  pattern        = "?ERROR ?CRITICAL"

  metric_transformation {
    name          = "ErrosNoLog"
    namespace     = local.namespace_logs
    value         = "1"
    default_value = "0"
  }
}

# Erros nos logs: soma da métrica dos metric filters. Qualquer linha de erro alarma:
# só a mensagem inválida da demonstração da DLQ gerou erro nos ensaios.
resource "aws_cloudwatch_metric_alarm" "erros_no_log" {
  alarm_name          = "${var.prefixo}-erros-no-log"
  alarm_description   = "Linha com ERROR ou CRITICAL nos logs do chat-api ou do order-worker"
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
