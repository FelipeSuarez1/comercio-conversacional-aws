# Plataforma de Comércio Conversacional na AWS

Projeto semestral de CLOUD 101 (Insper): MVP de comércio conversacional em ECS sobre EC2.

- Etapa manual: AWS US East — Ohio (`us-east-2`)
- Etapa automatizada (Terraform): AWS South America — São Paulo (`sa-east-1`)

## Documentação

- [Proposta de arquitetura](docs/arquitetura.md)
- [Planejamento](docs/planejamento.md)

## Rodando localmente

Requer Docker com Compose. Os emuladores (DynamoDB Local e ElasticMQ) sobem junto; o LLM roda em modo `fake` por padrão, sem chave.

```bash
cp .env.example .env          # ajuste LLM_MODO=real e a chave só se quiser usar o LLM de verdade
docker compose up --build     # sobe tudo; o serviço seed cria as tabelas e o catálogo
bash scripts/smoke-test.sh    # em outro terminal: health, catálogo, pedido CONFIRMADO e REJEITADO
```

Documentação interativa da API: http://localhost:8000/docs

Para demonstrar a DLQ (requer `pip install -r scripts/requirements.txt`): `bash scripts/enviar-mensagem-invalida.sh --acompanhar`.

## Estrutura

```
app/
  chat-api/       # API de chat + tool calling com o LLM (atrás do ALB)
  order-worker/   # consumidor da fila de pedidos (SQS)
scripts/          # build-and-push, seed do catálogo, testes de carga
infra/
  bootstrap/      # bucket S3 do estado remoto
  modules/        # network, data, cluster, service, observability
  envs/sa-east-1/ # composição do ambiente de São Paulo
docs/
```
