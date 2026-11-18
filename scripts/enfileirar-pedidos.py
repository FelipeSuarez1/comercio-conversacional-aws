"""Cria N pedidos PENDENTE direto no DynamoDB e publica cada um na fila,
para demonstrar a escala do order-worker pela profundidade da fila.

Não passa pelo chat (não chama o LLM). Usa um produto com estoque alto e
quantidade 1, então os pedidos são confirmados até o estoque acabar; depois
disso viram REJEITADO, o que também é um resultado válido para a demo.
Rode o seed depois da demonstração para restaurar o estoque.

Uso (credenciais da AWS CLI):
    TABELA_PEDIDOS=cafe-pedidos TABELA_PRODUTOS=cafe-produtos \
    FILA_PEDIDOS_URL=<url da fila> AWS_REGION=<regiao> \
    python scripts/enfileirar-pedidos.py 6000
"""

import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import boto3

PRODUTO_ID = os.environ.get("PRODUTO_DEMO", "brasil-cerrado-mineiro")


def main():
    quantidade = int(sys.argv[1]) if len(sys.argv) > 1 else 6000
    regiao = os.environ["AWS_REGION"]
    dynamodb = boto3.resource("dynamodb", region_name=regiao)
    sqs = boto3.client("sqs", region_name=regiao)
    pedidos = dynamodb.Table(os.environ["TABELA_PEDIDOS"])
    fila = os.environ["FILA_PEDIDOS_URL"]

    produto = dynamodb.Table(os.environ["TABELA_PRODUTOS"]).get_item(
        Key={"produto_id": PRODUTO_ID})["Item"]
    preco = int(produto["preco_centavos"])

    # 1) Grava os pedidos em lotes de 25 (batch_writer)
    ids = [str(uuid.uuid4()) for _ in range(quantidade)]
    agora = datetime.now(timezone.utc).isoformat()
    with pedidos.batch_writer() as escritor:
        for pedido_id in ids:
            escritor.put_item(Item={
                "pedido_id": pedido_id,
                "conversa_id": "demo-carga",
                "itens": [{"produto_id": PRODUTO_ID, "nome": produto["nome"],
                           "quantidade": 1, "preco_unitario_centavos": preco}],
                "desconto_centavos": 0,
                "total_centavos": preco,
                "status": "PENDENTE",
                "criado_em": agora,
                "atualizado_em": agora,
            })
    print(f"{quantidade} pedidos gravados; publicando na fila...", flush=True)

    # 2) Publica em lotes de 10 (limite do SendMessageBatch), 16 lotes em paralelo
    def publicar(lote):
        entradas = [{"Id": str(i), "MessageBody": json.dumps({"pedido_id": pid})}
                    for i, pid in enumerate(lote)]
        sqs.send_message_batch(QueueUrl=fila, Entries=entradas)

    lotes = [ids[i:i + 10] for i in range(0, len(ids), 10)]
    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(publicar, lotes))
    print(f"Pronto: {quantidade} pedidos na fila.")


if __name__ == "__main__":
    main()
