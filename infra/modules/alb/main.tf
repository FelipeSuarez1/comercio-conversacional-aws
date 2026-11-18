# Ponto de entrada público: distribui as requisições entre as tasks do chat-api nas 2 AZs
resource "aws_lb" "this" {
  name               = "${var.prefixo}-alb"
  load_balancer_type = "application"
  internal           = false
  subnets            = var.subnets_publicas
  security_groups    = [var.sg_alb_id]

  tags = {
    Name = "${var.prefixo}-alb"
  }
}

# Tipo instance: o ECS registra cada task como instância + porta dinâmica (a porta daqui é só obrigatória)
resource "aws_lb_target_group" "chat_api" {
  name                 = "${var.prefixo}-chat-api-tg"
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "instance"
  vpc_id               = var.vpc_id
  deregistration_delay = 30

  health_check {
    protocol            = "HTTP"
    path                = "/health"
    matcher             = "200"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = {
    Name = "${var.prefixo}-chat-api-tg"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.chat_api.arn
  }
}
