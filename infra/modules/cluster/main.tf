# Passos 3 (roles da instância e de execução), 7 (repositórios ECR) e 8 (cluster,
# Launch Template, ASG e Capacity Provider) do docs/ohio-manual.md.

# Tags padrão do provider: o Launch Template e o ASG não as propagam sozinhos
# para instâncias e volumes, então são repassadas explicitamente.
data "aws_default_tags" "atual" {}

# ---------------------------------------------------------------- IAM

data "aws_iam_policy_document" "confianca_ec2" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

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

# Role da instância: agente do ECS registrar a instância; SSM para acesso sem SSH
resource "aws_iam_role" "instancia" {
  name               = "${var.prefixo}-ecs-instance-role"
  description        = "Instancias EC2 do cluster ECS"
  assume_role_policy = data.aws_iam_policy_document.confianca_ec2.json
}

resource "aws_iam_role_policy_attachment" "instancia" {
  for_each = toset([
    "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role",
    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
  ])

  role       = aws_iam_role.instancia.name
  policy_arn = each.value
}

resource "aws_iam_instance_profile" "instancia" {
  name = "${var.prefixo}-ecs-instance-profile"
  role = aws_iam_role.instancia.name
}

# Role de execução das tasks: ECR, logs e só o segredo do LLM
resource "aws_iam_role" "execucao" {
  name               = "${var.prefixo}-ecs-task-execution"
  description        = "Execucao das tasks: ECR, logs e segredo do LLM"
  assume_role_policy = data.aws_iam_policy_document.confianca_ecs_tasks.json
}

resource "aws_iam_role_policy_attachment" "execucao" {
  role       = aws_iam_role.execucao.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "ler_segredo" {
  statement {
    sid       = "LerSomenteOSegredoDoLLM"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.segredo_arn]
  }
}

resource "aws_iam_role_policy" "ler_segredo" {
  name   = "${var.prefixo}-ler-segredo-llm"
  role   = aws_iam_role.execucao.id
  policy = data.aws_iam_policy_document.ler_segredo.json
}

# ---------------------------------------------------------------- ECR

resource "aws_ecr_repository" "repo" {
  for_each = toset(["chat-api", "order-worker"])

  name         = "${var.prefixo}/${each.key}"
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

# ---------------------------------------------------------------- Cluster

resource "aws_ecs_cluster" "this" {
  name = "${var.prefixo}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# ---------------------------------------------------------------- Launch Template

# AMI ECS-optimized (Amazon Linux 2023) recomendada para a região
data "aws_ssm_parameter" "ami_ecs" {
  name = "/aws/service/ecs/optimized-ami/amazon-linux-2023/recommended/image_id"
}

resource "aws_launch_template" "ecs" {
  name        = "${var.prefixo}-ecs-lt"
  description = "ECS AL2023 ${var.tipo_instancia}"

  image_id      = data.aws_ssm_parameter.ami_ecs.insecure_value
  instance_type = var.tipo_instancia

  iam_instance_profile {
    name = aws_iam_instance_profile.instancia.name
  }

  network_interfaces {
    device_index                = 0
    associate_public_ip_address = false
    security_groups             = [var.sg_ecs_id]
    delete_on_termination       = true
  }

  # IMDSv2 obrigatório; hop limit 1 impede os containers (bridge) de herdar a role da instância
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  # Registra a instância no cluster certo (sem isso iria para o "default").
  # Referenciar o cluster cria a dependência: o LT/ASG somem antes do cluster.
  user_data = base64encode(<<-EOT
    #!/bin/bash
    echo "ECS_CLUSTER=${aws_ecs_cluster.this.name}" >> /etc/ecs/ecs.config
  EOT
  )

  tag_specifications {
    resource_type = "instance"
    tags          = merge(data.aws_default_tags.atual.tags, { Name = "${var.prefixo}-ecs" })
  }

  tag_specifications {
    resource_type = "volume"
    tags          = merge(data.aws_default_tags.atual.tags, { Name = "${var.prefixo}-ecs" })
  }
}

# ---------------------------------------------------------------- Auto Scaling Group

resource "aws_autoscaling_group" "ecs" {
  name                = "${var.prefixo}-asg"
  min_size            = var.asg_min
  max_size            = var.asg_max
  desired_capacity    = var.asg_desejado
  vpc_zone_identifier = var.subnets_privadas

  # EC2: o ASG troca instâncias com falha de hardware/SO; a aplicação fica com ECS e ALB
  health_check_type         = "EC2"
  health_check_grace_period = 0

  # Pré-requisito do managed termination protection
  protect_from_scale_in = true

  # Como o --force-delete de Ohio: apaga mesmo com instâncias protegidas
  force_delete = true

  launch_template {
    id      = aws_launch_template.ecs.id
    version = "$Latest"
  }

  # Métricas do grupo no CloudWatch (usadas por alarme da observabilidade)
  metrics_granularity = "1Minute"
  enabled_metrics = [
    "GroupMinSize",
    "GroupMaxSize",
    "GroupDesiredCapacity",
    "GroupInServiceInstances",
    "GroupPendingInstances",
    "GroupStandbyInstances",
    "GroupTerminatingInstances",
    "GroupTotalInstances",
    "GroupInServiceCapacity",
    "GroupPendingCapacity",
    "GroupStandbyCapacity",
    "GroupTerminatingCapacity",
    "GroupTotalCapacity",
  ]

  # O ECS adiciona esta tag ao gerenciar o ASG; declarada para não gerar drift
  tag {
    key                 = "AmazonECSManaged"
    value               = "true"
    propagate_at_launch = true
  }

  # Tags padrão no próprio ASG (como em Ohio, sem propagar: as instâncias recebem pelo LT)
  dynamic "tag" {
    for_each = data.aws_default_tags.atual.tags
    content {
      key                 = tag.key
      value               = tag.value
      propagate_at_launch = false
    }
  }

  lifecycle {
    # Quem ajusta a capacidade é o managed scaling do Capacity Provider
    ignore_changes = [desired_capacity]
  }

  # As instâncias precisam das permissões para se registrar; na destruição,
  # o ASG some antes de as políticas serem desanexadas.
  depends_on = [aws_iam_role_policy_attachment.instancia]
}

# ---------------------------------------------------------------- Capacity Provider

# Referencia o ASG: na destruição o CP (e a associação abaixo) somem antes do ASG
resource "aws_ecs_capacity_provider" "this" {
  name = "${var.prefixo}-cp"

  auto_scaling_group_provider {
    auto_scaling_group_arn         = aws_autoscaling_group.ecs.arn
    managed_termination_protection = "ENABLED"
    managed_draining               = "ENABLED"

    managed_scaling {
      status          = "ENABLED"
      target_capacity = 100
    }
  }
}

# Estratégia padrão do cluster: tudo vai para o CP
resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = [aws_ecs_capacity_provider.this.name]

  default_capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.this.name
    weight            = 1
    base              = 0
  }
}
