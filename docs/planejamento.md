# Planejamento do projeto

Baseado em [arquitetura.md](arquitetura.md). As fases estão em ordem de dependência; sem prazos porque as datas de entrega não foram informadas.

## Estratégia: C primeiro, depois B

Primeiro entregamos tudo o que o enunciado exige (seção 3) no formato mais simples: isso é o conceito C. Depois subimos para B **somando** peças, sem refazer nada. Por isso a topologia (2 serviços, ALB, SQS + DLQ, DynamoDB, Capacity Provider, 3 roles) já nasce igual à da proposta B: ela é obrigatória de qualquer forma.

Itens marcados com **[B]** nas fases ficam para a segunda rodada.

| Tema | Versão C (primeira entrega) | Upgrade para B |
|---|---|---|
| Interface | Swagger do FastAPI (`/docs`) para conversar | Página HTML simples |
| Tools | `buscar_produtos`, `criar_pedido` | + `consultar_estoque`, `consultar_pedido` |
| Worker | Consome a fila, baixa o estoque e confirma o pedido; DLQ configurada na fila | Escrita condicional (idempotência e estoque nunca negativo), heartbeat no health check |
| Escala de tasks | Target tracking por **CPU** nos dois serviços | `chat-api` por requisições no ALB; `order-worker` por profundidade da fila |
| Escala de instâncias | Capacity Provider com managed scaling | Igual, + managed draining e scale-in protection ajustados e demonstrados |
| Logs | `awslogs`, texto simples | JSON com `conversa_id` / `pedido_id` (correlação) |
| Alarmes | Um alarme por item exigido (tasks, cluster, ASG, ALB, fila, erros), notificação por e-mail | Limiares calibrados com teste de carga |
| IAM | 3 tipos de role separados (instância, execução, tarefa), políticas por serviço | Políticas restritas a cada tabela, fila e segredo |
| Imagens no Terraform | `build-and-push` rodado antes do `apply` | Build e push disparados pelo próprio `apply` |
| Terraform | Um só ambiente em `envs/sa-east-1`, poucas variáveis | Módulos reutilizáveis e parametrização completa |

## Fase 0 — Preparação

- [ ] Validar a proposta de arquitetura com o grupo (domínio, LLM, DynamoDB).
- [ ] Confirmar com o professor: (a) uso de API de LLM externa; (b) se o bucket de estado do Terraform pode ser criado fora do código principal; (c) se um script de comandos da AWS CLI conta como etapa manual.
- [ ] Conta AWS com budget e alarme de custo configurados.
- [x] Repositório Git: `app/chat-api`, `app/order-worker`, `scripts/`, `infra/`, `docs/`, publicado como repositório privado no GitHub.
- [ ] Obter a chave da API do LLM (local: `.env`; AWS: Secrets Manager).

## Fase 1 — Aplicação (local)

- [ ] `chat-api`: FastAPI, `/health`, `/chat`, loop de tool calling. Página HTML **[B]**.
- [ ] Tools: `buscar_produtos`, `criar_pedido`. `consultar_estoque` e `consultar_pedido` **[B]**.
- [ ] `order-worker`: consumo da fila, baixa de estoque, confirmação do pedido. Escrita condicional, idempotência e heartbeat **[B]**.
- [ ] Logs JSON com `conversa_id` / `pedido_id` / `request_id` **[B]**.
- [ ] Dockerfiles e `docker-compose` com DynamoDB Local e ElasticMQ (ou LocalStack).
- [ ] Script de carga do catálogo (`seed`).
- [ ] Testar a jornada completa. Mensagem duplicada, estoque insuficiente e LLM indisponível **[B]**.

**Pronto quando**: a conversa consulta o catálogo e grava um pedido que o worker confirma.

## Fase 2 — Etapa manual em Ohio (us-east-2)

Console e AWS CLI apenas. **Anotar cada recurso criado** — a relação é um entregável e vira o checklist do Terraform.

1. [ ] Rede: VPC, 4 sub-redes, IGW, NAT, tabelas de rotas, endpoints de S3 e DynamoDB.
2. [ ] Security groups `alb-sg` e `ecs-sg`.
3. [ ] IAM: role da instância, role de execução, uma task role por serviço.
4. [ ] Secrets Manager: chave do LLM.
5. [ ] DynamoDB: 3 tabelas + seed.
6. [ ] SQS: fila de pedidos + DLQ com redrive policy.
7. [ ] ECR: 2 repositórios; build e push das imagens.
8. [ ] ECS: cluster, Launch Template, ASG, Capacity Provider.
9. [ ] ALB, target group e listener.
10. [ ] Task definitions e os 2 serviços.
11. [ ] Auto scaling dos serviços.
12. [ ] Log groups, Container Insights, alarmes, tópico SNS.

**Entregáveis**: aplicação no ar, diagrama, relação de recursos, demonstração.

## Fase 3 — Roteiro de demonstração (usado nas duas etapas)

| Demonstração | Como provocar | O que mostrar |
|---|---|---|
| Jornada do MVP | Conversa no navegador | Pedido no DynamoDB, estoque decrementado |
| Escala de tasks (chat) | Carga HTTP com `hey` ou `k6` | Tasks subindo de 2 para N |
| Escala de tasks (worker) | Script que enfileira centenas de pedidos | Fila enchendo, workers subindo, fila esvaziando |
| Escala de instâncias | Consequência das duas anteriores | Tasks em `PROVISIONING`, ASG subindo de 2 para 3–4 |
| Scale-in e drenagem | Parar a carga | Instância em `DRAINING`, tasks realocadas, instância removida |
| Task defeituosa | `aws ecs stop-task` ou endpoint que derruba o processo | ECS repõe a task, ALB segue respondendo |
| Instância perdida | Terminar uma EC2 pelo console | ASG repõe, tasks voltam, dados intactos |
| DLQ | Enviar mensagem malformada | 3 tentativas, mensagem na DLQ, alarme disparado |

- [ ] Escrever os scripts de carga em `scripts/`.
- [ ] Ensaiar uma vez e cronometrar (o scale-out de EC2 leva alguns minutos).
- [ ] Capturar prints/gráficos do CloudWatch como evidência.

## Fase 4 — Terraform em São Paulo (sa-east-1)

Estrutura sugerida:

```
infra/
  bootstrap/        # bucket S3 do estado (aplicado uma vez)
  modules/
    network/        # VPC, sub-redes, rotas, NAT, endpoints, SGs
    data/           # DynamoDB, SQS + DLQ, Secrets Manager (só o recipiente)
    cluster/        # ECR, cluster, Launch Template, ASG, Capacity Provider, IAM
    service/        # task definition, serviço, auto scaling, logs (reutilizado 2x)
    observability/  # alarmes, SNS
  envs/sa-east-1/   # main.tf, backend.tf, terraform.tfvars
```

- [ ] Backend S3 com lock nativo (`use_lockfile`).
- [ ] Região, CIDRs, tipo de instância, limites de escala e tags como variáveis.
- [ ] AZs via `data "aws_availability_zones"`; AMI via `data "aws_ssm_parameter"`.
- [ ] Valor do segredo fora do Terraform: variável `sensitive` vinda de `TF_VAR_...`, ou `put-secret-value` documentado.
- [ ] Imagens: `terraform_data` com `local-exec` chamando o `build-and-push`, e os serviços dependendo dele — assim um único `apply` sobe tudo.
- [ ] `force_delete` nos ECRs e ordem de dependência correta entre ASG e Capacity Provider para o `destroy` funcionar de primeira.
- [ ] Buscar por `us-east-2` no repositório inteiro: não pode haver nenhuma ocorrência.
- [ ] Ciclo completo `apply` → demonstração → `destroy` → `apply` de novo, em conta limpa.

**Pronto quando**: um `terraform apply` em `sa-east-1` entrega a aplicação funcionando sem tocar no console.

## Fase 5 — Apresentação final

- [ ] Diagrama atualizado e slide de justificativas (decomposição, dimensionamento, NAT único).
- [ ] Repetir o roteiro da Fase 3 em São Paulo.
- [ ] Mostrar o `apply` (ou gravação dele, por causa do tempo) e o estado remoto.
- [ ] Destruir os dois ambientes após a avaliação.

## Riscos

| Risco | Mitigação |
|---|---|
| Custo esquecido (NAT e EC2 ligados) | Budget com alerta; derrubar Ohio entre ensaios; `destroy` em São Paulo |
| `destroy` travado por ASG / Capacity Provider | Testar o ciclo completo cedo, não na véspera |
| Scale-out de EC2 lento na demo | Ensaiar e ter gráficos prontos como reserva |
| Limite ou falha da API do LLM na demo | Timeout, retentativa e mensagem amigável; chave com crédito verificado antes |
| Task não cabe na instância | Conferir a conta de memória da seção 5 da arquitetura ao mudar reservas |

## Divisão sugerida do trabalho

- **Aplicação**: `chat-api`, tools, worker, testes locais.
- **Infra Ohio**: rede, ECS, ALB, relação de recursos.
- **Dados e observabilidade**: DynamoDB, SQS, alarmes, scripts de carga.
- **Terraform**: começa pelos módulos de rede em paralelo à Fase 2, usando a relação de recursos como checklist.
