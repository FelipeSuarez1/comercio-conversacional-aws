# Ambiente de São Paulo: a mesma arquitetura montada à mão em Ohio
# (docs/ohio-manual.md), agora em Terraform e sem nenhuma dependência de lá.

locals {
  # Nome do serviço do worker, usado na métrica de escala (o módulo ainda não existe
  # quando a métrica é montada, então não dá para usar o output dele).
  nome_servico_worker = "${var.prefixo}-order-worker"

  # Ambiente das tasks: docs/contratos.md e infra/ohio/taskdef-*.json
  ambiente_comum = {
    AWS_REGION       = var.regiao
    TABELA_PRODUTOS  = module.data.tabela_produtos_nome
    TABELA_PEDIDOS   = module.data.tabela_pedidos_nome
    FILA_PEDIDOS_URL = module.data.fila_url
    LOG_LEVEL        = var.log_level
  }

  # URL e modelo vazios (modo fake) ficam fora da task definition.
  ambiente_chat_api = merge(local.ambiente_comum, {
    for k, v in {
      TABELA_CONVERSAS = module.data.tabela_conversas_nome
      LLM_MODO         = var.llm_modo
      LLM_BASE_URL     = var.llm_base_url
      MODEL_ID         = var.model_id
    } : k => v if v != ""
  })
}

module "network" {
  source = "../../modules/network"

  prefixo  = var.prefixo
  cidr_vpc = var.cidr_vpc
}

module "alb" {
  source = "../../modules/alb"

  prefixo          = var.prefixo
  vpc_id           = module.network.vpc_id
  subnets_publicas = module.network.subnets_publicas
  sg_alb_id        = module.network.sg_alb_id
}

module "data" {
  source = "../../modules/data"

  prefixo            = var.prefixo
  llm_modo           = var.llm_modo
  llm_api_key        = var.llm_api_key
  llm_api_key_versao = var.llm_api_key_versao
}

module "cluster" {
  source = "../../modules/cluster"

  prefixo          = var.prefixo
  subnets_privadas = module.network.subnets_privadas
  sg_ecs_id        = module.network.sg_ecs_id
  tipo_instancia   = var.tipo_instancia
  asg_min          = var.asg_min
  asg_max          = var.asg_max
  asg_desejado     = var.asg_desejado
  segredo_arn      = module.data.segredo_arn
}

# Build e push das imagens no próprio apply; os serviços usam o output e só
# são criados/atualizados depois do push.
module "images" {
  source = "../../modules/images"

  providers = {
    docker = docker
  }

  diretorio_app = "${path.root}/../../../app"
  repositorios = {
    "chat-api"     = module.cluster.ecr_chat_api_url
    "order-worker" = module.cluster.ecr_order_worker_url
  }
}

# Políticas das task roles (infra/ohio/politica-*-task.json), com os ARNs do módulo data

data "aws_iam_policy_document" "chat_api_task" {
  statement {
    sid       = "LerCatalogo"
    actions   = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"]
    resources = [module.data.tabela_produtos_arn]
  }

  statement {
    sid     = "GravarELerConversasEPedidos"
    actions = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"]
    resources = [
      module.data.tabela_conversas_arn,
      module.data.tabela_pedidos_arn,
    ]
  }

  statement {
    sid       = "EnfileirarPedido"
    actions   = ["sqs:SendMessage"]
    resources = [module.data.fila_arn]
  }
}

data "aws_iam_policy_document" "order_worker_task" {
  statement {
    sid       = "ConsumirFilaDePedidos"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [module.data.fila_arn]
  }

  statement {
    sid       = "LerPedido"
    actions   = ["dynamodb:GetItem"]
    resources = [module.data.tabela_pedidos_arn]
  }

  statement {
    sid     = "BaixarEstoqueEAtualizarPedido"
    actions = ["dynamodb:UpdateItem"]
    resources = [
      module.data.tabela_produtos_arn,
      module.data.tabela_pedidos_arn,
    ]
  }
}

module "chat_api" {
  source = "../../modules/service"

  prefixo                = var.prefixo
  nome                   = "chat-api"
  regiao                 = var.regiao
  cluster_nome           = module.cluster.cluster_nome
  cluster_arn            = module.cluster.cluster_arn
  capacity_provider_nome = module.cluster.capacity_provider_nome
  execution_role_arn     = module.cluster.execution_role_arn
  imagem                 = module.images.imagens["chat-api"]

  cpu             = 256
  memoria_reserva = 384
  memoria_limite  = 512

  ambiente = local.ambiente_chat_api
  # segredo_arn só fica disponível depois que o segredo tem valor (secret_version)
  segredos           = { LLM_API_KEY = module.data.segredo_arn }
  politica_task_json = data.aws_iam_policy_document.chat_api_task.json

  porta_container  = 8000
  target_group_arn = module.alb.target_group_arn

  desejado = 2
  minimo   = 2
  maximo   = 8

  # Duas políticas de target tracking: CPU média e requisições por task no ALB
  escala_cpu_alvo           = var.chat_api_cpu_alvo
  escala_requisicoes_alvo   = var.chat_api_requisicoes_por_task
  escala_requisicoes_rotulo = "${module.alb.alb_arn_suffix}/${module.alb.target_group_arn_suffix}"

  # O serviço só pode usar o target group depois que o listener existe
  # (o output target_group_arn não depende do listener).
  depends_on = [module.alb]
}

module "order_worker" {
  source = "../../modules/service"

  prefixo                = var.prefixo
  nome                   = "order-worker"
  regiao                 = var.regiao
  cluster_nome           = module.cluster.cluster_nome
  cluster_arn            = module.cluster.cluster_arn
  capacity_provider_nome = module.cluster.capacity_provider_nome
  execution_role_arn     = module.cluster.execution_role_arn
  imagem                 = module.images.imagens["order-worker"]

  cpu             = 128
  memoria_reserva = 192
  memoria_limite  = 256

  ambiente           = local.ambiente_comum
  politica_task_json = data.aws_iam_policy_document.order_worker_task.json

  # Mesmo health check do Dockerfile (app/order-worker/healthcheck.py)
  health_check_comando = ["CMD", "python", "healthcheck.py"]

  desejado = 1
  minimo   = 1
  maximo   = 4

  # Scale-out rápido para a fila não envelhecer; scale-in continua mais lento
  escala_cooldown_saida   = var.worker_cooldown_saida
  escala_cooldown_entrada = var.worker_cooldown_entrada

  # Backlog por task: mensagens visíveis / tasks rodando. Em Ohio o alvo era 100
  # (infra/ohio/escala-worker-fila.json); com 20 o worker reage a filas menores.
  escala_metrica_customizada = {
    alvo = var.worker_backlog_por_task
    metricas = [
      {
        id           = "visiveis"
        expressao    = null
        namespace    = "AWS/SQS"
        nome_metrica = "ApproximateNumberOfMessagesVisible"
        dimensoes    = { QueueName = module.data.fila_nome }
        estatistica  = "Sum"
        retorna      = false
        rotulo       = null
      },
      {
        id           = "tasks"
        expressao    = null
        namespace    = "ECS/ContainerInsights"
        nome_metrica = "RunningTaskCount"
        dimensoes = {
          ClusterName = module.cluster.cluster_nome
          ServiceName = local.nome_servico_worker
        }
        estatistica = "Average"
        retorna     = false
        rotulo      = null
      },
      {
        id           = "backlog_por_task"
        expressao    = "visiveis / tasks"
        namespace    = null
        nome_metrica = null
        dimensoes    = null
        estatistica  = null
        retorna      = true
        rotulo       = "Mensagens na fila por task do worker"
      },
    ]
  }
}

module "observability" {
  source = "../../modules/observability"

  prefixo                 = var.prefixo
  cluster_nome            = module.cluster.cluster_nome
  servicos                = [module.chat_api.servico_nome, module.order_worker.servico_nome]
  asg_nome                = module.cluster.asg_nome
  asg_min                 = var.asg_min
  alb_arn_suffix          = module.alb.alb_arn_suffix
  target_group_arn_suffix = module.alb.target_group_arn_suffix
  fila_nome               = module.data.fila_nome
  dlq_nome                = module.data.dlq_nome
  log_groups              = [module.chat_api.log_group_nome, module.order_worker.log_group_nome]
  email_alertas           = var.email_alertas
}
