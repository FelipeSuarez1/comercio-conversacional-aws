#!/usr/bin/env bash
# Demonstração da DLQ no ambiente local (ElasticMQ).
#
# Envia para a fila `pedidos` uma mensagem que não é JSON válido. O order-worker
# não consegue processá-la e não a apaga; ela volta à fila a cada 60 s
# (visibility timeout) e, depois de 3 recebimentos, vai para `pedidos-dlq`.
# Isso leva uns 3 a 4 minutos.
#
# Uso:  bash scripts/enviar-mensagem-invalida.sh               # só envia
#       bash scripts/enviar-mensagem-invalida.sh --acompanhar  # envia e mostra as filas até a DLQ receber
#
# Requer boto3 na máquina:  pip install -r scripts/requirements.txt

set -euo pipefail

# Só para o emulador local: credenciais falsas e endereço visto a partir do host.
export AWS_REGION=us-east-1
export AWS_ACCESS_KEY_ID=local
export AWS_SECRET_ACCESS_KEY=local
export SQS_ENDPOINT_URL="${SQS_ENDPOINT_URL:-http://localhost:9324}"

if [ -n "${PYTHON:-}" ]; then :; elif python3 -c "" >/dev/null 2>&1; then PYTHON=python3; else PYTHON=python; fi

"$PYTHON" - "${1:-}" <<'EOF'
import os
import sys
import time

import boto3

endpoint = os.environ["SQS_ENDPOINT_URL"]
fila = f"{endpoint}/000000000000/pedidos"
dlq = f"{endpoint}/000000000000/pedidos-dlq"
sqs = boto3.client("sqs", region_name=os.environ["AWS_REGION"], endpoint_url=endpoint)


def contar(url):
    attrs = sqs.get_queue_attributes(
        QueueUrl=url,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    return int(attrs["ApproximateNumberOfMessages"]) + int(attrs["ApproximateNumberOfMessagesNotVisible"])


dlq_antes = contar(dlq)
resposta = sqs.send_message(QueueUrl=fila, MessageBody="isto nao e um pedido valido {")
print(f"Mensagem malformada enviada para a fila pedidos (id {resposta['MessageId']}).")

if sys.argv[1] != "--acompanhar":
    print("Acompanhe os logs do worker:  docker compose logs -f order-worker")
    print("Ou use --acompanhar para enviar e esperar a mensagem chegar na DLQ.")
    sys.exit(0)

for _ in range(40):  # até ~5 minutos
    na_dlq = contar(dlq)
    print(f"fila pedidos: {contar(fila)} | pedidos-dlq: {na_dlq}")
    if na_dlq > dlq_antes:
        print("A mensagem chegou na DLQ.")
        sys.exit(0)
    time.sleep(8)

print("A mensagem ainda não chegou na DLQ. O order-worker está rodando?")
sys.exit(1)
EOF
