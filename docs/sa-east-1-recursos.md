# Relação de recursos — São Paulo (sa-east-1)

Etapa automatizada, criada pelo Terraform em `infra/envs/sa-east-1` (roteiro em [terraform.md](terraform.md)). É a mesma arquitetura de Ohio ([ohio-recursos.md](ohio-recursos.md)), sem dependência de lá.

Lista gerada a partir do state (`terraform -chdir=infra/envs/sa-east-1 state list`) com o ambiente no ar: **74 recursos gerenciados** em 7 módulos, mais 12 data sources. Prefixo `cafe`; todos os recursos recebem as tags padrão do provider `Projeto=cafe` e `Etapa=terraform`. IDs e ARNs não são listados: saem de `terraform state show <recurso>` ou `terraform output`.

Para conferir de novo (somente leitura):

```bash
terraform -chdir=infra/envs/sa-east-1 state list
terraform -chdir=infra/envs/sa-east-1 output
```

## Saídas (`terraform output`)

| Output | Valor |
|---|---|
| `url_alb` | `http://cafe-alb-<id>.sa-east-1.elb.amazonaws.com` |
| `cluster_nome` | `cafe-cluster` |
| `ecr_chat_api_url` | `<conta>.dkr.ecr.sa-east-1.amazonaws.com/cafe/chat-api` |
| `ecr_order_worker_url` | `<conta>.dkr.ecr.sa-east-1.amazonaws.com/cafe/order-worker` |
| `fila_url` | `https://sqs.sa-east-1.amazonaws.com/<conta>/cafe-pedidos` |
| `segredo_arn` | `arn:aws:secretsmanager:sa-east-1:<conta>:secret:cafe/llm-api-key-<sufixo>` |
| `tabela_produtos_nome` | `cafe-produtos` |

## Bootstrap — `infra/bootstrap` (state local, aplicado uma vez)

| Recurso Terraform | Nome na AWS | Para que serve |
|---|---|---|
| `aws_s3_bucket.tfstate` | `cafe-tfstate-<conta>-sa-east-1` | Bucket do state remoto do ambiente (`force_destroy = false`) |
| `aws_s3_bucket_versioning.tfstate` | — | Versionamento: recupera versões anteriores do state |
| `aws_s3_bucket_server_side_encryption_configuration.tfstate` | — | Criptografia em repouso (SSE-S3, AES256) |
| `aws_s3_bucket_public_access_block.tfstate` | — | Bloqueia qualquer acesso público ao bucket |

O state do ambiente fica em `sa-east-1/terraform.tfstate` nesse bucket, com trava nativa do S3 (`use_lockfile`).

## `module.network` — rede e security groups (24)

| Recurso Terraform | Nome na AWS | Para que serve |
|---|---|---|
| `aws_vpc.principal` | `cafe-vpc` | VPC `10.0.0.0/16`, DNS hostnames ligado |
| `aws_subnet.publica[0]` | `cafe-publica-1` | `10.0.0.0/24`, 1ª AZ: ALB e NAT |
| `aws_subnet.publica[1]` | `cafe-publica-2` | `10.0.1.0/24`, 2ª AZ: ALB |
| `aws_subnet.privada[0]` | `cafe-privada-1` | `10.0.10.0/24`, 1ª AZ: instâncias ECS |
| `aws_subnet.privada[1]` | `cafe-privada-2` | `10.0.11.0/24`, 2ª AZ: instâncias ECS |
| `aws_internet_gateway.igw` | `cafe-igw` | Entrada/saída de internet das sub-redes públicas |
| `aws_eip.nat` | `cafe-nat-eip` | IP público fixo do NAT |
| `aws_nat_gateway.nat` | `cafe-nat` | Saída para a internet das privadas (1 só, decisão de custo) |
| `aws_route_table.publica` | `cafe-rt-publica` | Tabela das sub-redes públicas |
| `aws_route.publica_internet` | — | `0.0.0.0/0` → IGW |
| `aws_route_table_association.publica[0..1]` (2) | — | Liga as 2 públicas à `cafe-rt-publica` |
| `aws_route_table.privada` | `cafe-rt-privada` | Tabela das sub-redes privadas (e rotas dos endpoints) |
| `aws_route.privada_nat` | — | `0.0.0.0/0` → NAT |
| `aws_route_table_association.privada[0..1]` (2) | — | Liga as 2 privadas à `cafe-rt-privada` |
| `aws_vpc_endpoint.s3` | `cafe-vpce-s3` | Endpoint Gateway: S3 (camadas do ECR) sem passar pelo NAT |
| `aws_vpc_endpoint.dynamodb` | `cafe-vpce-dynamodb` | Endpoint Gateway: DynamoDB sem passar pelo NAT |
| `aws_security_group.alb` | `cafe-alb-sg` | SG do ALB |
| `aws_security_group.ecs` | `cafe-ecs-sg` | SG das instâncias ECS |
| `aws_vpc_security_group_ingress_rule.alb_http` | — | `cafe-alb-sg`: entra TCP 80 de `0.0.0.0/0` |
| `aws_vpc_security_group_egress_rule.alb_para_ecs` | — | `cafe-alb-sg`: sai 32768–65535 só para `cafe-ecs-sg` |
| `aws_vpc_security_group_ingress_rule.ecs_do_alb` | — | `cafe-ecs-sg`: entra 32768–65535 só de `cafe-alb-sg` |
| `aws_vpc_security_group_egress_rule.ecs_https` | — | `cafe-ecs-sg`: sai TCP 443 (ECR, ECS, SSM, SQS, CloudWatch, LLM) |

## `module.alb` — ponto de entrada (3)

| Recurso Terraform | Nome na AWS | Para que serve |
|---|---|---|
| `aws_lb.this` | `cafe-alb` | Application Load Balancer público nas 2 sub-redes públicas |
| `aws_lb_target_group.chat_api` | `cafe-chat-api-tg` | Alvos do `chat-api` (tipo `instance`, porta dinâmica), health check `GET /health`, deregistration delay 30 s |
| `aws_lb_listener.http` | — | HTTP 80 → `cafe-chat-api-tg` |

## `module.data` — dados, fila e segredo (6)

| Recurso Terraform | Nome na AWS | Para que serve |
|---|---|---|
| `aws_dynamodb_table.produtos` | `cafe-produtos` | Catálogo e estoque (chave `produto_id`), on-demand |
| `aws_dynamodb_table.pedidos` | `cafe-pedidos` | Pedidos e status (chave `pedido_id`), on-demand |
| `aws_dynamodb_table.conversas` | `cafe-conversas` | Histórico das conversas (`conversa_id` + `ts`), on-demand |
| `aws_sqs_queue.pedidos` | `cafe-pedidos` | Fila de pedidos: visibility 60 s, long polling 20 s, DLQ após 3 recebimentos |
| `aws_sqs_queue.pedidos_dlq` | `cafe-pedidos-dlq` | DLQ, retenção de 14 dias |
| `aws_secretsmanager_secret.llm_api_key` | `cafe/llm-api-key` | Recipiente da chave do LLM; o valor é gravado fora do Terraform (`put-secret-value`) |

## `module.cluster` — IAM base, ECR e capacidade (14)

| Recurso Terraform | Nome na AWS | Para que serve |
|---|---|---|
| `aws_iam_role.instancia` | `cafe-sa-east-1-ecs-instance-role` | Role das instâncias EC2 |
| `aws_iam_role_policy_attachment.instancia[...]` (2) | — | `AmazonEC2ContainerServiceforEC2Role` (agente ECS) e `AmazonSSMManagedInstanceCore` (acesso sem SSH) |
| `aws_iam_instance_profile.instancia` | `cafe-sa-east-1-ecs-instance-profile` | Liga a role às instâncias do Launch Template |
| `aws_iam_role.execucao` | `cafe-sa-east-1-ecs-task-execution` | Role de execução das tasks |
| `aws_iam_role_policy_attachment.execucao` | — | `AmazonECSTaskExecutionRolePolicy` (pull no ECR, logs) |
| `aws_iam_role_policy.ler_segredo` | `cafe-ler-segredo-llm` | Inline na role de execução: `GetSecretValue` só no segredo do LLM |
| `aws_ecr_repository.repo["chat-api"]` | `cafe/chat-api` | Imagens do `chat-api` (scan on push, `force_delete`) |
| `aws_ecr_repository.repo["order-worker"]` | `cafe/order-worker` | Imagens do `order-worker` (scan on push, `force_delete`) |
| `aws_ecs_cluster.this` | `cafe-cluster` | Cluster ECS com Container Insights ligado |
| `aws_launch_template.ecs` | `cafe-ecs-lt` | AMI ECS-optimized AL2023 (via SSM), `t3.small`, sem IP público, IMDSv2 com hop limit 1, user data com `ECS_CLUSTER` |
| `aws_autoscaling_group.ecs` | `cafe-asg` | 2 a 4 instâncias nas 2 privadas, scale-in protection, métricas do grupo ligadas |
| `aws_ecs_capacity_provider.this` | `cafe-cp` | Managed scaling (target 100), managed termination protection e managed draining |
| `aws_ecs_cluster_capacity_providers.this` | — | Associa `cafe-cp` ao cluster como estratégia padrão |

As roles levam a região no nome (`cafe-sa-east-1-...`) porque IAM é global na conta e as roles de Ohio usam `cafe-...`.

## `module.chat_api` — serviço `chat-api` (7)

| Recurso Terraform | Nome na AWS | Para que serve |
|---|---|---|
| `aws_cloudwatch_log_group.this` | `/ecs/cafe/chat-api` | Logs do container (`awslogs`), retenção de 7 dias |
| `aws_iam_role.task` | `cafe-sa-east-1-chat-api-task` | Task role do `chat-api` |
| `aws_iam_role_policy.task` | `cafe-chat-api-acesso` | Leitura em `cafe-produtos`; Put/Get/Query em `cafe-conversas` e `cafe-pedidos`; `sqs:SendMessage` na fila |
| `aws_ecs_task_definition.this` | `cafe-chat-api` | `bridge`, porta 8000 → dinâmica, CPU 256, memória 384/512 MiB, `LLM_API_KEY` do Secrets Manager |
| `aws_ecs_service.this` | `cafe-chat-api` | Serviço no `cafe-cp` ligado ao target group; spread por AZ + binpack por memória; deploy 100/200 com circuit breaker |
| `aws_appautoscaling_target.this` | `service/cafe-cluster/cafe-chat-api` | Limites de 2 a 8 tasks |
| `aws_appautoscaling_policy.cpu[0]` | `cafe-chat-api-cpu60` | Target tracking em CPU média de 60% |

## `module.order_worker` — serviço `order-worker` (7)

| Recurso Terraform | Nome na AWS | Para que serve |
|---|---|---|
| `aws_cloudwatch_log_group.this` | `/ecs/cafe/order-worker` | Logs do container (`awslogs`), retenção de 7 dias |
| `aws_iam_role.task` | `cafe-sa-east-1-order-worker-task` | Task role do `order-worker` |
| `aws_iam_role_policy.task` | `cafe-order-worker-acesso` | Receive/Delete/GetQueueAttributes na fila; GetItem em `cafe-pedidos`; UpdateItem em `cafe-produtos` e `cafe-pedidos` |
| `aws_ecs_task_definition.this` | `cafe-order-worker` | `bridge`, sem porta, CPU 128, memória 192/256 MiB, health check `python healthcheck.py` |
| `aws_ecs_service.this` | `cafe-order-worker` | Serviço no `cafe-cp`; mesmo posicionamento e deploy do `chat-api` |
| `aws_appautoscaling_target.this` | `service/cafe-cluster/cafe-order-worker` | Limites de 1 a 4 tasks |
| `aws_appautoscaling_policy.metrica[0]` | `cafe-order-worker-metrica` | Target tracking em mensagens visíveis na fila por task (`visiveis / tasks`), alvo 100 |

## `module.observability` — alarmes e notificação (13)

| Recurso Terraform | Nome na AWS | Para que serve |
|---|---|---|
| `aws_sns_topic.alertas` | `cafe-alertas` | Destino dos 10 alarmes (sem assinatura de e-mail no Terraform) |
| `aws_cloudwatch_metric_alarm.tasks_abaixo["cafe-chat-api"]` | `cafe-chat-api-tasks-abaixo` | `DesiredTaskCount - RunningTaskCount > 0` por 3 min |
| `aws_cloudwatch_metric_alarm.tasks_abaixo["cafe-order-worker"]` | `cafe-order-worker-tasks-abaixo` | Idem, para o worker |
| `aws_cloudwatch_metric_alarm.cluster_reserva["CPUReservation"]` | `cafe-cluster-CPUReservation-alta` | Reserva de CPU do cluster > 85% por 5 min |
| `aws_cloudwatch_metric_alarm.cluster_reserva["MemoryReservation"]` | `cafe-cluster-MemoryReservation-alta` | Reserva de memória do cluster > 85% por 5 min |
| `aws_cloudwatch_metric_alarm.asg_instancias_abaixo` | `cafe-asg-instancias-abaixo` | `GroupInServiceInstances` < 2 |
| `aws_cloudwatch_metric_alarm.alb_5xx` | `cafe-alb-5xx` | 5 ou mais `HTTPCode_Target_5XX_Count` em 1 min |
| `aws_cloudwatch_metric_alarm.tg_hosts_nao_saudaveis` | `cafe-tg-hosts-nao-saudaveis` | `UnHealthyHostCount` > 0 |
| `aws_cloudwatch_metric_alarm.fila_mensagem_antiga` | `cafe-fila-mensagem-antiga` | Mensagem mais antiga da fila > 5 min |
| `aws_cloudwatch_metric_alarm.dlq_com_mensagens` | `cafe-dlq-com-mensagens` | DLQ com mensagem visível |
| `aws_cloudwatch_log_metric_filter.erros["/ecs/cafe/chat-api"]` | `cafe-chat-api-erros` | Conta linhas com `ERROR` no log do `chat-api` (métrica `Cafe/ErrosNoLog`) |
| `aws_cloudwatch_log_metric_filter.erros["/ecs/cafe/order-worker"]` | `cafe-order-worker-erros` | Idem, no log do `order-worker` |
| `aws_cloudwatch_metric_alarm.erros_no_log` | `cafe-erros-no-log` | Soma de `Cafe/ErrosNoLog` > 0 em 1 min |

## Raiz do ambiente — data sources (não criam nada)

| Data source | Para que serve |
|---|---|
| `data.aws_iam_policy_document.chat_api_task` | Monta a política da task role do `chat-api` com os ARNs do módulo `data` |
| `data.aws_iam_policy_document.order_worker_task` | Idem, para o `order-worker` |
| `module.network.data.aws_availability_zones.disponiveis` | Descobre as 2 AZs (nada de nome fixo) |
| `module.network.data.aws_region.atual` / `module.cluster.data.aws_region.atual` | Região atual (nomes dos endpoints e das roles) |
| `module.cluster.data.aws_ssm_parameter.ami_ecs` | AMI ECS-optimized AL2023 recomendada para a região |
| `module.cluster.data.aws_default_tags.atual` | Repassa as tags padrão para instâncias e volumes |
| `module.cluster.data.aws_iam_policy_document.*` (3), `module.chat_api/order_worker.data.aws_iam_policy_document.confianca_ecs_tasks` (2) | Políticas de confiança (EC2, ECS tasks) e leitura do segredo |

## Criados automaticamente pela AWS (fora do state)

| Recurso | Origem | Observação |
|---|---|---|
| 2 instâncias EC2 `cafe-ecs` (até 4) e seus volumes | ASG `cafe-asg` | Quantidade ajustada pelo Capacity Provider; tags vêm do Launch Template |
| Alarmes `TargetTracking-service/cafe-cluster/...` (4: alta e baixa, por serviço) | Políticas de auto scaling das tasks | Somem com as políticas no `destroy` |
| Política `ECSManagedAutoScalingPolicy-...` + 2 alarmes `TargetTracking-...` no ASG | Managed scaling do `cafe-cp` | Somem com o Capacity Provider |
| Lifecycle hook `ecs-managed-draining-...` no ASG | Managed draining do `cafe-cp` | Idem |
| Interfaces de rede do ALB e do NAT | ELB e EC2 | Liberadas ao apagar ALB/NAT |
| Service-linked roles (ECS, Auto Scaling, Application Auto Scaling, ELB) | Cada serviço, no primeiro uso | Já existiam na conta desde Ohio; não precisam ser apagadas |
| Log group `/aws/ecs/containerinsights/cafe-cluster/performance` | Container Insights | Não é apagado pelo `destroy`; remover à mão |
| Valor do segredo `cafe/llm-api-key` | `aws secretsmanager put-secret-value` (passo 3.3 do [terraform.md](terraform.md)) | Nunca passa pelo Terraform nem pelo state |
| Itens do catálogo em `cafe-produtos` | `scripts/seed.py` (passo 3.4) | Rodar de novo reseta o estoque |
| Imagens `cafe/chat-api:<tag>` e `cafe/order-worker:<tag>` | `docker build` + `docker push` (passo 3.2) | Apagadas com os repositórios (`force_delete`) |
