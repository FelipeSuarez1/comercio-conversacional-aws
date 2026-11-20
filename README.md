# Plataforma de Comércio Conversacional na AWS

Projeto semestral de CLOUD 101 (Insper). MVP de uma loja de cafés especiais em que o cliente conversa com um vendedor de IA: a IA busca produtos no catálogo por *tool calling*, cria o pedido, e um worker assíncrono baixa o estoque e confirma ou rejeita o pedido. Roda em ECS sobre EC2, montado duas vezes: à mão pela AWS CLI em Ohio (`us-east-2`) e com Terraform em São Paulo (`sa-east-1`). Entrega atual: conceito C.

## Arquitetura

- `chat-api` (FastAPI) atrás de um ALB público; conversa com uma API de LLM externa (chave no Secrets Manager) e grava conversa e pedido `PENDENTE` no DynamoDB.
- Pedido vai para uma fila SQS (com DLQ após 3 falhas); o `order-worker` consome, baixa o estoque com escrita condicional e marca `CONFIRMADO` ou `REJEITADO`.
- VPC em 2 AZs: ALB e 1 NAT nas públicas, instâncias ECS (`t3.small`, ASG 2–4 com Capacity Provider) nas privadas.
- Escala das tasks: `chat-api` por CPU 60% (2 a 8), `order-worker` por mensagens na fila por task (alvo 100, 1 a 4). Em São Paulo (Terraform): `chat-api` também por requisições no ALB (1500 por task/min) e `order-worker` com alvo 20 e scale-out em 30 s.
- Container Insights, logs no CloudWatch e 10 alarmes publicando num tópico SNS (em São Paulo, assinatura de e-mail opcional por `email_alertas` e limiares calibrados com os testes de carga).

Detalhes, diagrama e justificativas: [docs/arquitetura.md](docs/arquitetura.md).

## Documentação

| Documento | Conteúdo |
|---|---|
| [arquitetura.md](docs/arquitetura.md) | Arquitetura, diagrama, dimensionamento e decisões (o que é C e o que é B) |
| [planejamento.md](docs/planejamento.md) | Fases do projeto, checklist e roteiro de demonstração |
| [contratos.md](docs/contratos.md) | Nomes de tabelas, formato das mensagens e variáveis de ambiente |
| [ohio-manual.md](docs/ohio-manual.md) | Etapa 1: roteiro passo a passo com AWS CLI em Ohio |
| [ohio-recursos.md](docs/ohio-recursos.md) | Relação dos recursos criados em Ohio |
| [terraform.md](docs/terraform.md) | Etapa 2: bootstrap, `apply`, validação e `destroy` em São Paulo |
| [sa-east-1-recursos.md](docs/sa-east-1-recursos.md) | Relação dos recursos criados pelo Terraform em São Paulo |
| [evidencias.md](docs/evidencias.md) | Evidências do roteiro de demonstração (gráficos e prints) |

## Rodando localmente

Requer Docker com Compose. Sobem juntos DynamoDB Local, ElasticMQ (SQS), um serviço `seed` que cria as tabelas e o catálogo, o `chat-api` e o `order-worker`. O LLM roda em modo `fake` por padrão, sem chave.

```bash
cp .env.example .env          # LLM_MODO=real + LLM_API_KEY, LLM_BASE_URL e MODEL_ID só para usar o LLM de verdade
docker compose up --build
bash scripts/smoke-test.sh    # em outro terminal: health, catálogo, pedido CONFIRMADO e REJEITADO
```

- API e Swagger (interface de conversa da versão C): http://localhost:8000/docs
- Testes do worker: `pip install -r app/order-worker/requirements-dev.txt` e `pytest app/order-worker/tests`.
- DLQ local (requer `pip install -r scripts/requirements.txt`): `bash scripts/enviar-mensagem-invalida.sh --acompanhar`.

## Etapa 1 — Ohio (manual)

Toda a infraestrutura criada pela AWS CLI, passo a passo, com verificação em cada passo e desmontagem no final: [docs/ohio-manual.md](docs/ohio-manual.md). Recursos criados: [docs/ohio-recursos.md](docs/ohio-recursos.md). Os JSONs usados pelos comandos ficam em `infra/ohio/`.

## Etapa 2 — São Paulo (Terraform)

A mesma arquitetura em Terraform, sem dependência de Ohio, com state remoto em S3: [docs/terraform.md](docs/terraform.md). Recursos criados: [docs/sa-east-1-recursos.md](docs/sa-east-1-recursos.md).

```bash
terraform -chdir=infra/bootstrap apply                            # uma vez: bucket do state
terraform -chdir=infra/envs/sa-east-1 init -backend-config=backend.hcl
terraform -chdir=infra/envs/sa-east-1 apply                       # primeiro apply em etapas: ver terraform.md
```

## Roteiro de demonstração

Cenários (jornada, escala de tasks e de instâncias, scale-in, falha de task e de instância, DLQ): [Fase 3 do planejamento](docs/planejamento.md#fase-3--roteiro-de-demonstração-usado-nas-duas-etapas). Comandos na seção **Demonstrações** do [ohio-manual.md](docs/ohio-manual.md). Evidências: [docs/evidencias.md](docs/evidencias.md).

## Estrutura

```
app/
  chat-api/            # FastAPI: /chat com tool calling, /produtos, /pedidos/{id}, /health
  order-worker/        # consumidor da fila de pedidos + testes (pytest)
scripts/
  seed.py              # cria/recarrega o catálogo (local ou AWS)
  smoke-test.sh        # teste de ponta a ponta (LLM fake)
  carga.py             # carga HTTP para escalar o chat-api
  enfileirar-pedidos.py  # milhares de pedidos na fila para escalar o order-worker
  enviar-mensagem-invalida.sh  # demonstração da DLQ (local)
  local/               # config do ElasticMQ
infra/
  ohio/                # JSONs e user data da etapa manual
  bootstrap/           # bucket S3 do state do Terraform
  modules/             # network, alb, data, cluster, service, observability
  envs/sa-east-1/      # composição do ambiente de São Paulo
docs/                  # documentação (tabela acima) e evidencias/
docker-compose.yml     # ambiente local
.env.example           # modelo do .env local (nunca commitar o .env)
```
