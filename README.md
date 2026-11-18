# Plataforma de Comércio Conversacional na AWS

Projeto semestral de CLOUD 101 (Insper): MVP de comércio conversacional em ECS sobre EC2.

- Etapa manual: AWS US East — Ohio (`us-east-2`)
- Etapa automatizada (Terraform): AWS South America — São Paulo (`sa-east-1`)

## Documentação

- [Proposta de arquitetura](docs/arquitetura.md)
- [Planejamento](docs/planejamento.md)

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
