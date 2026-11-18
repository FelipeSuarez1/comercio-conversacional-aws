# Proposta de arquitetura — Comércio Conversacional na AWS

Alvo: conceito **B em todas as dimensões**, com alguns itens baratos de nível A onde o custo de implementação é baixo (marcados com **[A]**).

Entrega em duas rodadas: primeiro a versão C, que usa esta mesma topologia no formato mais simples, e depois o upgrade para B. O que entra em cada rodada está em [planejamento.md](planejamento.md#estratégia-c-primeiro-depois-b).

**Estado atual**: versão C implementada em Ohio (à mão, [ohio-manual.md](ohio-manual.md)) e em São Paulo (Terraform, [terraform.md](terraform.md)). O texto abaixo descreve o que está no ar; trechos marcados **(B, não implementado)** são da segunda rodada e ainda não existem.

## 1. Domínio e escopo do MVP

**Loja de cafés especiais** ("Grão"): o cliente conversa com um vendedor de IA que recomenda cafés, consulta preço e estoque, aplica desconto por quantidade e registra o pedido.

Motivos da escolha: catálogo pequeno e fácil de popular, estoque numérico (permite demonstrar concorrência e consistência), e uma regra de negociação simples (desconto progressivo) que não exige lógica complexa.

Jornada mínima:

1. Cliente: "quero um café frutado, até R$ 60" → IA chama `buscar_produtos`.
2. Cliente: "tem 3 pacotes do Etiópia?" → IA chama `consultar_estoque` **(B, não implementado)**; na versão C o estoque vem no resultado de `buscar_produtos`.
3. Cliente: "fecha 3" → IA chama `criar_pedido` → pedido gravado como `PENDENTE` e enviado para a fila.
4. O worker reserva o estoque e muda o pedido para `CONFIRMADO` ou `REJEITADO`.
5. Cliente: "meu pedido foi confirmado?" → IA chama `consultar_pedido` **(B, não implementado)**; na versão C o status é consultado em `GET /pedidos/{pedido_id}`.

## 2. Stack

| Camada | Escolha | Por quê |
|---|---|---|
| Linguagem | Python 3.12 + FastAPI | Simples, boto3 nativo, um único idioma para os dois serviços |
| IA | API de LLM externa com *tool calling*, modelo definido por variável `MODEL_ID` | Independe de região (não há risco de o modelo não existir em sa-east-1) e gera um segredo real para o Secrets Manager |
| Persistência | DynamoDB (on-demand) | Sem instância para gerenciar, barato, escrita condicional resolve estoque e idempotência |
| Mensageria | SQS standard + DLQ | Requisito direto da rubrica, integração simples |
| Front | Versão C: Swagger do FastAPI (`/docs`). Página HTML estática servida pelo próprio `chat-api`: **(B, não implementado)** | A interface não é avaliada |

Alternativa para a IA: Amazon Bedrock (dispensa chave e usa IAM), mas a disponibilidade de modelos difere entre Ohio e São Paulo — vira dependência regional a ser tratada.

## 3. Topologia

```mermaid
flowchart LR
  U[Cliente] -->|HTTP 80| ALB
  subgraph VPC[VPC 10.0.0.0/16 — 2 AZs]
    subgraph PUB[Sub-redes públicas]
      ALB[Application Load Balancer]
      NAT[NAT Gateway]
    end
    subgraph PRIV[Sub-redes privadas — ASG de instâncias ECS]
      API[Serviço chat-api]
      WK[Serviço order-worker]
    end
  end
  ALB --> API
  API -->|tool calling| LLM[API do LLM]
  API --> DDB[(DynamoDB)]
  API -->|SendMessage| SQS[[SQS pedidos]]
  SQS --> WK
  SQS -.->|3 falhas| DLQ[[DLQ]]
  WK --> DDB
  API & WK --> CW[CloudWatch Logs / métricas / alarmes]
  API -.-> SM[Secrets Manager]
```

### Serviços ECS

| | `chat-api` | `order-worker` |
|---|---|---|
| Responsabilidade | Front, endpoint `/chat`, orquestra o LLM e as tools, grava conversa e pedido `PENDENTE` | Consome a fila, reserva estoque, confirma ou rejeita o pedido |
| Entrada | ALB (síncrono) | SQS (assíncrono) |
| Perfil de carga | I/O intenso, latência dominada pelo LLM, muitas conexões abertas | Rajadas curtas conforme a fila |
| Métrica de escala | CPU média 60% (target tracking) | Mensagens visíveis na fila por task (target tracking, alvo 100) |
| Tasks min / max | 2 / 8 | 1 / 4 |
| Health check | `GET /health` no target group | `healthCheck` do container (heartbeat do loop de consumo) |

Justificativa da decomposição:

- **Isolamento de falhas**: se o LLM ficar lento ou fora do ar, só o `chat-api` degrada; pedidos já enfileirados continuam sendo processados. Se o worker cair, a conversa continua e os pedidos esperam na fila.
- **Escala independente**: o chat escala por CPU, o worker por profundidade de fila. Escalar o chat por requisições no ALB (`ALBRequestCountPerTarget`): **(B, não implementado)**.
- **Consistência**: toda alteração de estoque passa por um único componente.

O `/health` **não** chama o LLM nem o DynamoDB — do contrário, uma indisponibilidade do LLM derrubaria todas as tasks de uma vez.

### Modelo de dados (DynamoDB)

Tabelas on-demand, com o prefixo do ambiente no nome (`cafe-produtos` etc.). Atributos completos em [contratos.md](contratos.md).

| Tabela | Chave | Conteúdo |
|---|---|---|
| `produtos` | `produto_id` | nome, descrição, notas sensoriais, preço, `estoque` |
| `conversas` | `conversa_id` + `ts` (ISO 8601) | mensagens do cliente e da IA, tools chamadas |
| `pedidos` | `pedido_id` | conversa, itens, total, `status`, timestamps |

### Tratamento de falhas e duplicidade

- `chat-api` gera o `pedido_id` (UUID) e grava com `attribute_not_exists(pedido_id)`.
- O worker só processa se `status = PENDENTE` (escrita condicional) → mensagem duplicada vira no-op **[A]**.
- Baixa de estoque com condição `estoque >= quantidade` → nunca fica negativo, mesmo com workers concorrentes **[A]**.
- Fila: long polling de 20 s, visibility timeout de 60 s, `maxReceiveCount = 3`, depois DLQ.
- LLM: timeout de 20 s e uma retentativa; em falha, resposta amigável e nenhum pedido criado.

## 4. Rede

| Recurso | Configuração |
|---|---|
| VPC | `10.0.0.0/16`, 2 AZs obtidas dinamicamente |
| Sub-redes públicas | `10.0.0.0/24`, `10.0.1.0/24` — ALB e NAT |
| Sub-redes privadas | `10.0.10.0/24`, `10.0.11.0/24` — instâncias ECS |
| Saída para internet | **1 NAT Gateway** (ECR, CloudWatch, SQS, API do LLM) |
| VPC endpoints | Gateway para S3 e DynamoDB (gratuitos) |

Um único NAT é uma decisão consciente de custo: a perda da AZ do NAT interromperia a saída das instâncias. Vale citar na apresentação como trade-off; um NAT por AZ seria o passo para nível A.

Security groups:

| SG | Entrada | Saída |
|---|---|---|
| `alb-sg` | TCP 80 de `0.0.0.0/0` | Portas 32768–65535 para `ecs-sg` |
| `ecs-sg` | Portas 32768–65535 **somente de `alb-sg`** | TCP 443 para `0.0.0.0/0` |

Sem SSH: acesso às instâncias via SSM Session Manager.

## 5. ECS sobre EC2 e capacidade

| Item | Valor |
|---|---|
| Instância | `t3.small` (2 vCPU, 2 GiB → ~2048 CPU units e ~1900 MiB registráveis) |
| AMI | ECS-optimized Amazon Linux 2023, lida do parâmetro público SSM `/aws/service/ecs/optimized-ami/amazon-linux-2023/recommended/image_id` |
| ASG | min 2 / desejado 2 / máx 4, nas duas sub-redes privadas |
| Capacity Provider | managed scaling ligado, `targetCapacity = 100`, managed termination protection e managed draining ligados |
| Modo de rede das tasks | `bridge` com porta dinâmica (evita o limite de ENIs do `awsvpc` em instâncias pequenas) |
| Posicionamento | `spread` por AZ, depois `binpack` por memória |
| Deploy | `minimumHealthyPercent = 100`, `maximumPercent = 200`, circuit breaker com rollback |

Reservas por task:

| Serviço | CPU | Memória (reserva / limite) |
|---|---|---|
| `chat-api` | 256 | 384 / 512 MiB |
| `order-worker` | 128 | 192 / 256 MiB |

Conta de capacidade: uma `t3.small` comporta cerca de 3 tasks `chat-api` + 2 `order-worker` (limitado por memória). Com 2 instâncias, o estado base (2 + 1 tasks) usa ~25% da memória reservável; o máximo (8 + 4 tasks) pede 3840 MiB, mais que as ~3826 MiB de 2 instâncias, forçando o Capacity Provider a subir para 3–4 instâncias. É exatamente esse salto que demonstra o segundo nível de elasticidade.

`spread` por AZ garante que as 2 tasks do chat fiquem em instâncias diferentes (disponibilidade); `binpack` concentra o restante e libera instâncias inteiras para o scale-in.

## 6. Segurança

| Role | Permissões |
|---|---|
| Instância EC2 | `AmazonEC2ContainerServiceforEC2Role` + `AmazonSSMManagedInstanceCore` |
| Execução das tasks | Pull no ECR, escrita em logs, leitura **apenas** do segredo da chave do LLM |
| Task `chat-api` | Leitura em `produtos`; leitura/escrita em `conversas` e `pedidos`; `sqs:SendMessage` na fila de pedidos |
| Task `order-worker` | `sqs:ReceiveMessage/DeleteMessage/GetQueueAttributes` na fila; `dynamodb:GetItem` em `pedidos`; `dynamodb:UpdateItem` em `produtos` e `pedidos` (cobre o `TransactWriteItems`) |

Chave do LLM no Secrets Manager, injetada pelo ECS no campo `secrets` da task definition — nunca em código, imagem ou `.tfvars`. O Terraform cria só o recipiente do segredo; o valor é gravado com `put-secret-value` e não passa pelo state.

Nomes: IAM é global na conta, então no Terraform as roles e o instance profile levam a região (`cafe-sa-east-1-ecs-instance-role`, `cafe-sa-east-1-chat-api-task` etc.) para não colidir com as de Ohio, criadas à mão como `cafe-...`.

## 7. Observabilidade

- **Logs**: um log group por serviço (`/ecs/cafe/<serviço>`, driver `awslogs`, retenção de 7 dias), em texto simples (`data nível logger mensagem`). Logs em JSON com `conversa_id`, `pedido_id` e `request_id` para correlacionar chat → fila → worker: **(B, não implementado)**.
- **Container Insights** ligado no cluster.
- **Alarmes**: 10 alarmes, todos publicando no tópico SNS `cafe-alertas`. Em Ohio o e-mail do grupo foi assinado à mão (passo 12.1 do [ohio-manual.md](ohio-manual.md)); em São Paulo o Terraform cria o tópico **sem assinatura**. Notificação por e-mail gerenciada no código: **(B, não implementado)**.

| Área | Alarme | Quantidade |
|---|---|---|
| Tasks | `DesiredTaskCount - RunningTaskCount` > 0 por 3 min (Container Insights), por serviço | 2 |
| Cluster | Reserva de CPU e de memória > 85% por 5 min | 2 |
| ASG | `GroupInServiceInstances` < mínimo (2) | 1 |
| ALB | `HTTPCode_Target_5XX_Count` ≥ 5 em 1 min; `UnHealthyHostCount` > 0 | 2 |
| Fila | Idade da mensagem mais antiga > 5 min; DLQ com mensagens > 0 | 2 |
| Aplicação | Metric filter sobre linhas com `ERROR` nos 2 log groups (métrica `Cafe/ErrosNoLog`), soma > 0 | 1 |

Além desses, as políticas de target tracking criam sozinhas os alarmes `TargetTracking-*` (das tasks e do ASG); eles não notificam ninguém. Limiares calibrados com teste de carga: **(B, não implementado)**.

## 8. Imagens e portabilidade regional

- Um repositório ECR por serviço **em cada região** (`cafe/chat-api`, `cafe/order-worker`).
- Build e push com `docker build --platform linux/amd64` + `docker push`, tag = hash curto do commit, para o ECR da região em uso (passo 7 do [ohio-manual.md](ohio-manual.md) e passo 3.2 do [terraform.md](terraform.md)). São Paulo nunca referencia o ECR de Ohio. Script `build-and-push` disparado pelo próprio `terraform apply`: **(B, não implementado)**; na versão C o build/push é feito antes do `apply`.
- Nada fixo no código: região, AZs, AMI, ARNs e URLs de fila chegam por variáveis de ambiente, variáveis do Terraform ou data sources.
- State do Terraform em bucket S3 próprio (`infra/bootstrap`), com versionamento, criptografia e trava nativa (`use_lockfile`).

## 9. O que fica de fora (caminho para A)

HTTPS com ACM e domínio próprio, NAT por AZ, métricas de negócio customizadas (pedidos/min, taxa de rejeição), dashboard, teste de carga com análise quantitativa, reprocessamento automático da DLQ.
