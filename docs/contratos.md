# Contratos entre componentes

Fonte única de verdade para nomes de tabelas, formato de mensagens e variáveis de ambiente. `chat-api`, `order-worker`, scripts e infraestrutura seguem este documento.

## Variáveis de ambiente

Nenhum valor regional ou segredo fica fixo no código: tudo vem do ambiente.

| Variável | Usada por | Exemplo local | Observação |
|---|---|---|---|
| `AWS_REGION` | todos | `us-east-1` | Obrigatória. Na AWS vem da task definition |
| `DYNAMODB_ENDPOINT_URL` | todos | `http://dynamodb:8000` | Só local; ausente na AWS |
| `SQS_ENDPOINT_URL` | todos | `http://sqs:9324` | Só local; ausente na AWS |
| `TABELA_PRODUTOS` | todos | `produtos` | |
| `TABELA_PEDIDOS` | todos | `pedidos` | |
| `TABELA_CONVERSAS` | `chat-api` | `conversas` | |
| `FILA_PEDIDOS_URL` | `chat-api`, `order-worker` | `http://sqs:9324/000000000000/pedidos` | |
| `LLM_MODO` | `chat-api` | `real` ou `fake` | `fake` dispensa chave (testes e carga) |
| `LLM_API_KEY` | `chat-api` | (no `.env`, nunca commitado) | Na AWS vem do Secrets Manager |
| `LLM_BASE_URL` | `chat-api` | URL do provedor | Qualquer API compatível com o formato OpenAI de chat completions |
| `MODEL_ID` | `chat-api` | id do modelo do provedor | |
| `LOG_LEVEL` | todos | `INFO` | |

## Tabelas DynamoDB

Valores monetários sempre em **centavos (inteiro)** para evitar ponto flutuante.

### `produtos`

| Atributo | Tipo | Nota |
|---|---|---|
| `produto_id` | S | Chave de partição (ex.: `etiopia-yirgacheffe`) |
| `nome` | S | |
| `descricao` | S | |
| `origem` | S | País/região |
| `torra` | S | `clara`, `media`, `escura` |
| `notas` | L de S | Notas sensoriais (ex.: `frutado`, `chocolate`) |
| `preco_centavos` | N | Preço de um pacote de 250 g |
| `estoque` | N | Pacotes disponíveis; nunca negativo |

### `pedidos`

| Atributo | Tipo | Nota |
|---|---|---|
| `pedido_id` | S | Chave de partição, UUID gerado pelo `chat-api` |
| `conversa_id` | S | |
| `itens` | L de M | `{produto_id, nome, quantidade, preco_unitario_centavos}` |
| `desconto_centavos` | N | |
| `total_centavos` | N | Já com desconto |
| `status` | S | `PENDENTE` → `CONFIRMADO` ou `REJEITADO` |
| `motivo` | S | Preenchido quando `REJEITADO` |
| `criado_em`, `atualizado_em` | S | ISO 8601 UTC |

### `conversas`

| Atributo | Tipo | Nota |
|---|---|---|
| `conversa_id` | S | Chave de partição, UUID |
| `ts` | S | Chave de ordenação: ISO 8601 UTC com microssegundos |
| `papel` | S | `cliente` ou `vendedor` |
| `conteudo` | S | Texto da mensagem |

## Regra comercial

- Preço sempre lido do banco, nunca do texto do modelo.
- Desconto: 10% sobre o item quando a quantidade do mesmo produto for **3 ou mais**.

## Fila `pedidos`

- Corpo da mensagem (JSON): `{"pedido_id": "<uuid>", "conversa_id": "<uuid>"}`.
- O worker relê o pedido no DynamoDB; a mensagem só carrega ids. `conversa_id` serve só para correlacionar logs e é opcional: mensagens só com `pedido_id` (scripts, mensagens antigas) continuam válidas, e o worker usa o `conversa_id` gravado no pedido.
- Visibility timeout 60 s, long polling 20 s, `maxReceiveCount = 3`, depois `pedidos-dlq`.
- Mensagem malformada ou pedido inexistente: o worker **não** apaga a mensagem; ela volta à fila e, após 3 tentativas, vai para a DLQ.

## Processamento do pedido (`order-worker`)

1. Lê o pedido. Se o `status` não for `PENDENTE`, apaga a mensagem e segue (mensagem duplicada).
2. Em uma única `TransactWriteItems`: para cada item, `estoque = estoque - quantidade` com condição `estoque >= quantidade`; e o pedido passa para `CONFIRMADO` com condição `status = PENDENTE`.
3. Se a transação falhar por condição de estoque, o pedido passa para `REJEITADO` com `motivo = "estoque insuficiente"`.
4. Apaga a mensagem só depois de gravar o resultado.

## Ferramentas do vendedor (tool calling)

| Ferramenta | Argumentos | Devolve |
|---|---|---|
| `buscar_produtos` | `texto`, `preco_maximo_reais` (ambos opcionais) | Até 10 produtos (id, nome, notas, preço, estoque) |
| `criar_pedido` | `itens: [{produto_id, quantidade}]` | `pedido_id`, total, desconto, `status = PENDENTE` |
| `consultar_estoque` | `produto_id` ou `nome` | `produto_id`, nome, `estoque`, `disponivel`, preço; `outros_parecidos` se o nome casar com mais de um |
| `consultar_pedido` | `pedido_id` | Os dados de `GET /pedidos/{id}`: `status`, `motivo` (se `REJEITADO`), itens, desconto, total, datas |

Erros de validação voltam ao modelo como `{"erro": "..."}`. No modo `fake`, "estoque", "disponível" ou "quantos pacotes" chamam `consultar_estoque`; um id de pedido ou a palavra "pedido" chama `consultar_pedido` (sem id na mensagem, usa o último id citado na conversa).

## Logs (os dois serviços)

Um objeto JSON por linha no stdout (o driver `awslogs` envia cada linha como um evento). O traceback de um erro vai no campo `excecao`, na mesma linha.

```json
{"timestamp": "2026-11-20T17:25:11.652Z", "nivel": "INFO", "servico": "order-worker", "logger": "order-worker", "mensagem": "resultado CONFIRMADO; mensagem apagada", "message_id": "...", "pedido_id": "...", "conversa_id": "...", "resultado": "CONFIRMADO"}
```

| Campo | Quando |
|---|---|
| `timestamp`, `nivel`, `servico`, `logger`, `mensagem` | Sempre. `nivel` é `DEBUG`, `INFO`, `WARNING`, `ERROR` ou `CRITICAL` |
| `request_id` | `chat-api`, em toda requisição (vem do header `X-Request-Id` ou é gerado; volta na resposta) |
| `conversa_id` | `chat-api` em todo log do `/chat`; `order-worker` a partir da mensagem ou do pedido |
| `pedido_id` | Criação, envio para a fila e consulta do pedido; todo o processamento no worker |
| `excecao` | Erros com traceback |

Correlação: filtrar por `pedido_id` (ou `conversa_id`) no CloudWatch Logs Insights, nos log groups dos dois serviços, mostra a conversa, o envio para a fila e o resultado no worker. O metric filter de erros (pattern `ERROR`) continua casando, porque a linha de erro contém `"nivel": "ERROR"`.

## HTTP do `chat-api` (porta 8000)

| Método e rota | Corpo / resposta |
|---|---|
| `GET /health` | `{"status": "ok"}`, sem tocar em banco ou LLM |
| `POST /chat` | Header opcional `X-Request-Id`. Entrada `{"conversa_id": opcional, "mensagem": "..."}`; saída `{"conversa_id", "resposta", "pedidos_criados": [ids]}` |
| `GET /produtos` | Lista do catálogo (apoio para demonstração) |
| `GET /pedidos/{pedido_id}` | Pedido completo (apoio para demonstração) |
