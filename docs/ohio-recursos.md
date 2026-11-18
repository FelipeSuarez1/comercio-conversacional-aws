# Relação de recursos criados — Ohio (us-east-2)

Etapa manual, criada pelo roteiro [ohio-manual.md](ohio-manual.md). Todos os recursos têm as tags `Projeto=cafe` e `Etapa=manual` (exceto onde indicado). A coluna **ID / ARN** é preenchida durante a criação; os valores ficam também em `infra/ohio/.ids.env` (fora do Git). Esta lista serve de checklist para a etapa em Terraform.

## Rede (passo 1)

| Tipo | Nome | Finalidade | ID / ARN |
|---|---|---|---|
| VPC | `cafe-vpc` | Rede isolada `10.0.0.0/16`, DNS hostnames ligado | |
| Sub-rede pública | `cafe-publica-1` | `10.0.0.0/24`, 1ª AZ: ALB e NAT | |
| Sub-rede pública | `cafe-publica-2` | `10.0.1.0/24`, 2ª AZ: ALB | |
| Sub-rede privada | `cafe-privada-1` | `10.0.10.0/24`, 1ª AZ: instâncias ECS | |
| Sub-rede privada | `cafe-privada-2` | `10.0.11.0/24`, 2ª AZ: instâncias ECS | |
| Internet Gateway | `cafe-igw` | Entrada/saída de internet das sub-redes públicas | |
| Elastic IP | `cafe-nat-eip` | IP público fixo do NAT Gateway | |
| NAT Gateway | `cafe-nat` | Saída para a internet das sub-redes privadas (1 só, decisão de custo) | |
| Tabela de rotas | `cafe-rt-publica` | `0.0.0.0/0` → IGW; associada às 2 públicas | |
| Tabela de rotas | `cafe-rt-privada` | `0.0.0.0/0` → NAT; associada às 2 privadas; rotas dos endpoints | |
| VPC endpoint (Gateway) | `cafe-vpce-s3` | Tráfego para o S3 (camadas do ECR) sem passar pelo NAT | |
| VPC endpoint (Gateway) | `cafe-vpce-dynamodb` | Tráfego para o DynamoDB sem passar pelo NAT | |

## Security groups (passo 2)

| Tipo | Nome | Finalidade | ID / ARN |
|---|---|---|---|
| Security group | `cafe-alb-sg` | Entrada TCP 80 de `0.0.0.0/0`; saída 32768–65535 só para `cafe-ecs-sg` | |
| Security group | `cafe-ecs-sg` | Entrada 32768–65535 só de `cafe-alb-sg`; saída TCP 443 | |

## IAM (passos 3 e 4)

| Tipo | Nome | Finalidade | ID / ARN |
|---|---|---|---|
| IAM role | `cafe-ecs-instance-role` | Instâncias EC2: agente do ECS (`AmazonEC2ContainerServiceforEC2Role`) e SSM (`AmazonSSMManagedInstanceCore`) | |
| Instance profile | `cafe-ecs-instance-profile` | Liga a role acima às instâncias do Launch Template | |
| IAM role | `cafe-ecs-task-execution` | Execução das tasks: pull no ECR e logs (`AmazonECSTaskExecutionRolePolicy`) | |
| Política inline | `cafe-ler-segredo-llm` | Na role de execução: `secretsmanager:GetSecretValue` só no segredo do LLM | — |
| IAM role | `cafe-chat-api-task` | Permissões do código do `chat-api` | |
| Política inline | `cafe-chat-api-acesso` | Leitura em `cafe-produtos`; Put/Get/Query em `cafe-conversas` e `cafe-pedidos`; `sqs:SendMessage` na fila | — |
| IAM role | `cafe-order-worker-task` | Permissões do código do `order-worker` | |
| Política inline | `cafe-order-worker-acesso` | Receive/Delete/GetQueueAttributes na fila; GetItem em `cafe-pedidos`; UpdateItem em `cafe-produtos` e `cafe-pedidos` | — |

## Dados e mensageria (passos 4 a 6)

| Tipo | Nome | Finalidade | ID / ARN |
|---|---|---|---|
| Segredo (Secrets Manager) | `cafe/llm-api-key` | Chave da API do LLM, injetada no `chat-api` como `LLM_API_KEY` | |
| Tabela DynamoDB | `cafe-produtos` | Catálogo e estoque (chave `produto_id`) | |
| Tabela DynamoDB | `cafe-pedidos` | Pedidos e status (chave `pedido_id`) | |
| Tabela DynamoDB | `cafe-conversas` | Histórico das conversas (chaves `conversa_id` + `ts`) | |
| Fila SQS | `cafe-pedidos-dlq` | Dead-letter queue: pedidos que falharam 3 vezes (retenção 14 dias) | |
| Fila SQS | `cafe-pedidos` | Pedidos para o worker (visibility 60 s, long polling 20 s, redrive após 3) | |

## Imagens (passo 7)

| Tipo | Nome | Finalidade | ID / ARN |
|---|---|---|---|
| Repositório ECR | `cafe/chat-api` | Imagens do `chat-api` (tag = hash curto do commit) | |
| Repositório ECR | `cafe/order-worker` | Imagens do `order-worker` | |

## Computação (passos 8 a 11)

| Tipo | Nome | Finalidade | ID / ARN |
|---|---|---|---|
| Cluster ECS | `cafe-cluster` | Cluster com Container Insights ligado | |
| Launch Template | `cafe-ecs-lt` | AMI ECS-optimized AL2023, `t3.small`, sem IP público, IMDSv2, user data `ECS_CLUSTER` | |
| Auto Scaling Group | `cafe-asg` | 2 a 4 instâncias nas sub-redes privadas, proteção de scale-in | |
| Capacity Provider | `cafe-cp` | Liga o ASG ao cluster: managed scaling (alvo 100%), termination protection, draining | |
| Application Load Balancer | `cafe-alb` | Ponto de entrada público (HTTP 80) nas 2 sub-redes públicas | |
| Target group | `cafe-chat-api-tg` | Alvos do `chat-api` (tipo instance, health check `/health`, deregistration 30 s) | |
| Listener | `cafe-alb` : 80 | HTTP 80 → `cafe-chat-api-tg` | |
| Log group | `/ecs/cafe/chat-api` | Logs do `chat-api` (7 dias) | |
| Log group | `/ecs/cafe/order-worker` | Logs do `order-worker` (7 dias) | |
| Task definition | `cafe-chat-api` | Container do chat: 256 CPU, 384/512 MiB, porta 8000 → dinâmica | |
| Task definition | `cafe-order-worker` | Container do worker: 128 CPU, 192/256 MiB, health check do heartbeat | |
| Serviço ECS | `cafe-chat-api` | 2 tasks atrás do ALB, spread por AZ + binpack | |
| Serviço ECS | `cafe-order-worker` | 1 task consumindo a fila | |
| Scalable target + política | `cafe-chat-api-cpu60` | Target tracking CPU 60%, 2 a 6 tasks (sem tag) | |
| Scalable target + política | `cafe-order-worker-cpu60` | Target tracking CPU 60%, 1 a 4 tasks (sem tag) | |

## Observabilidade (passo 12)

| Tipo | Nome | Finalidade | ID / ARN |
|---|---|---|---|
| Tópico SNS | `cafe-alertas` | Destino dos alarmes | |
| Assinatura SNS | e-mail do grupo | Recebe os alertas (confirmada pelo e-mail) | |
| Metric filter | `cafe-chat-api-erros` | Conta linhas `ERROR` em `/ecs/cafe/chat-api` → `Cafe/ErrosNoLog` | — |
| Metric filter | `cafe-order-worker-erros` | Conta linhas `ERROR` em `/ecs/cafe/order-worker` → `Cafe/ErrosNoLog` | — |
| Alarme | `cafe-chat-api-tasks-abaixo` | Tasks rodando < desejado no `chat-api` (Container Insights) | |
| Alarme | `cafe-order-worker-tasks-abaixo` | Tasks rodando < desejado no `order-worker` | |
| Alarme | `cafe-cluster-CPUReservation-alta` | Reserva de CPU do cluster > 85% | |
| Alarme | `cafe-cluster-MemoryReservation-alta` | Reserva de memória do cluster > 85% | |
| Alarme | `cafe-asg-instancias-abaixo` | `GroupInServiceInstances` < 2 | |
| Alarme | `cafe-alb-5xx` | `HTTPCode_Target_5XX_Count` ≥ 5 em 1 minuto | |
| Alarme | `cafe-tg-hosts-nao-saudaveis` | `UnHealthyHostCount` > 0 | |
| Alarme | `cafe-fila-mensagem-antiga` | `ApproximateAgeOfOldestMessage` > 300 s | |
| Alarme | `cafe-dlq-com-mensagens` | Mensagens visíveis na DLQ > 0 | |
| Alarme | `cafe-erros-no-log` | Alguma linha `ERROR` nos logs | |

## Criados automaticamente pela AWS (não criar nem apagar à mão)

| Tipo | Nome | Quem cria | Observação |
|---|---|---|---|
| Política de escala do ASG + 2 alarmes | `ECSManagedAutoScalingPolicy-...`, `TargetTracking-...` | Capacity Provider (managed scaling) | Somem ao apagar o Capacity Provider |
| Lifecycle hook de término do ASG | `ecs-managed-draining-...` | Capacity Provider (managed draining) | Idem |
| Alarmes de target tracking | `TargetTracking-service/cafe-cluster/...` (4) | Políticas de escala das tasks | Somem ao remover o scalable target |
| Instâncias EC2 e volumes EBS | `cafe-ecs` | ASG | Tags vêm do Launch Template |
| Interfaces de rede | ALB e NAT | ELB e EC2 | Liberadas ao apagar ALB/NAT |
| Service-linked roles | `AWSServiceRoleForECS`, `AWSServiceRoleForAutoScaling`, `AWSServiceRoleForApplicationAutoScaling_ECSService`, `AWSServiceRoleForElasticLoadBalancing` | Cada serviço, no primeiro uso | Ficam na conta; não precisam ser apagadas |
