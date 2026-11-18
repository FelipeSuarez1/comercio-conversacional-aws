locals {
  nome_completo = "${var.prefixo}-${var.nome}"

  # Listas em ordem alfabética para o JSON da task definition não mudar à toa
  environment = [for k in sort(keys(var.ambiente)) : { name = k, value = var.ambiente[k] }]
  secrets     = [for k in sort(keys(var.segredos)) : { name = k, valueFrom = var.segredos[k] }]

  # Campos opcionais do container: só entram no JSON quando não são null
  container_opcionais = {
    for k, v in {
      secrets = length(local.secrets) > 0 ? local.secrets : null
      portMappings = var.porta_container == null ? null : [
        { containerPort = var.porta_container, hostPort = 0, protocol = "tcp" }
      ]
      healthCheck = var.health_check_comando == null ? null : {
        command     = var.health_check_comando
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
    } : k => v if v != null
  }

  container = merge(
    {
      name              = var.nome
      image             = var.imagem
      essential         = true
      cpu               = var.cpu
      memoryReservation = var.memoria_reserva
      memory            = var.memoria_limite
      environment       = local.environment
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.this.name
          "awslogs-region"        = var.regiao
          "awslogs-stream-prefix" = var.nome
        }
      }
    },
    local.container_opcionais
  )
}

# Log group criado antes da task: a role de execução não pode criá-lo
resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.prefixo}/${var.nome}"
  retention_in_days = var.retencao_logs
}

# Task role: permissões do código dentro do container
data "aws_iam_policy_document" "confianca_ecs_tasks" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task" {
  name               = "${local.nome_completo}-task"
  description        = "Permissoes do codigo do ${var.nome}"
  assume_role_policy = data.aws_iam_policy_document.confianca_ecs_tasks.json
}

resource "aws_iam_role_policy" "task" {
  name   = "${local.nome_completo}-acesso"
  role   = aws_iam_role.task.id
  policy = var.politica_task_json
}

resource "aws_ecs_task_definition" "this" {
  family                   = local.nome_completo
  network_mode             = "bridge"
  requires_compatibilities = ["EC2"]
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions    = jsonencode([local.container])
}

resource "aws_ecs_service" "this" {
  name            = local.nome_completo
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desejado

  # Depende do Capacity Provider pelo nome (vem do módulo cluster)
  capacity_provider_strategy {
    capacity_provider = var.capacity_provider_nome
    weight            = 1
    base              = 0
  }

  # Espalha por AZ e depois concentra por memória (facilita o scale-in das instâncias)
  ordered_placement_strategy {
    type  = "spread"
    field = "attribute:ecs.availability-zone"
  }

  ordered_placement_strategy {
    type  = "binpack"
    field = "memory"
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  dynamic "load_balancer" {
    for_each = var.target_group_arn == null ? [] : [var.target_group_arn]

    content {
      target_group_arn = load_balancer.value
      container_name   = var.nome
      container_port   = var.porta_container
    }
  }

  health_check_grace_period_seconds = var.target_group_arn == null ? null : 60

  enable_ecs_managed_tags = true
  propagate_tags          = "SERVICE"

  lifecycle {
    # Quem ajusta o número de tasks é o auto scaling
    ignore_changes = [desired_count]
  }
}

# Auto scaling das tasks
resource "aws_appautoscaling_target" "this" {
  service_namespace  = "ecs"
  scalable_dimension = "ecs:service:DesiredCount"
  resource_id        = "service/${var.cluster_nome}/${aws_ecs_service.this.name}"
  min_capacity       = var.minimo
  max_capacity       = var.maximo
}

resource "aws_appautoscaling_policy" "cpu" {
  count = var.escala_cpu_alvo == null ? 0 : 1

  name               = "${local.nome_completo}-cpu${var.escala_cpu_alvo}"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.this.service_namespace
  scalable_dimension = aws_appautoscaling_target.this.scalable_dimension
  resource_id        = aws_appautoscaling_target.this.resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = var.escala_cpu_alvo
    scale_out_cooldown = 60
    scale_in_cooldown  = 120
    disable_scale_in   = false

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_policy" "metrica" {
  count = var.escala_metrica_customizada == null ? 0 : 1

  name               = "${local.nome_completo}-metrica"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.this.service_namespace
  scalable_dimension = aws_appautoscaling_target.this.scalable_dimension
  resource_id        = aws_appautoscaling_target.this.resource_id

  target_tracking_scaling_policy_configuration {
    target_value       = var.escala_metrica_customizada.alvo
    scale_out_cooldown = 60
    scale_in_cooldown  = 120
    disable_scale_in   = false

    customized_metric_specification {
      dynamic "metrics" {
        for_each = var.escala_metrica_customizada.metricas

        content {
          id          = metrics.value.id
          expression  = try(metrics.value.expressao, null)
          label       = try(metrics.value.rotulo, null)
          return_data = try(metrics.value.retorna, false)

          # Sem expressão: métrica do CloudWatch (metric_stat)
          dynamic "metric_stat" {
            for_each = try(metrics.value.expressao, null) == null ? [metrics.value] : []

            content {
              stat = metric_stat.value.estatistica

              metric {
                namespace   = metric_stat.value.namespace
                metric_name = metric_stat.value.nome_metrica

                dynamic "dimensions" {
                  for_each = try(metric_stat.value.dimensoes, {})

                  content {
                    name  = dimensions.key
                    value = dimensions.value
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
