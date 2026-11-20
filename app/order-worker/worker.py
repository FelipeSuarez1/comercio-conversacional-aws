"""Loop principal do order-worker: lê a fila de pedidos e processa um a um."""

import logging
import os
import signal
import sys
import threading
import time

import boto3

from config import ARQUIVO_HEARTBEAT, ErroDeConfiguracao, carregar_config
from log_json import configurar_logs, contexto_log
from processador import MensagemInvalida, PedidoInexistente, Processador, extrair_mensagem

log = logging.getLogger("order-worker")

# Ligado pelo SIGTERM (ECS drenando a task) ou SIGINT (Ctrl+C local).
parar = threading.Event()


def pedir_parada(numero_sinal, _quadro):
    log.info("sinal %s recebido; encerrando após a mensagem atual", signal.Signals(numero_sinal).name)
    parar.set()


def criar_cliente(servico, regiao, endpoint_url):
    argumentos = {"region_name": regiao}
    if endpoint_url:  # só no ambiente local
        argumentos["endpoint_url"] = endpoint_url
    return boto3.client(servico, **argumentos)


def gravar_heartbeat():
    # Grava num arquivo temporário e renomeia, para o healthcheck nunca ler um arquivo pela metade.
    temporario = ARQUIVO_HEARTBEAT + ".tmp"
    try:
        with open(temporario, "w") as arquivo:
            arquivo.write(str(time.time()))
        os.replace(temporario, ARQUIVO_HEARTBEAT)
    except OSError:
        log.exception("não foi possível gravar o heartbeat", extra={"arquivo": ARQUIVO_HEARTBEAT})


def tratar_mensagem(sqs, fila_url, processador, mensagem):
    """Processa uma mensagem e só a apaga se o resultado ficou gravado."""
    message_id = mensagem.get("MessageId")
    recebimentos = mensagem.get("Attributes", {}).get("ApproximateReceiveCount", "?")

    with contexto_log(message_id=message_id, recebimento=recebimentos):
        try:
            pedido_id, conversa_id = extrair_mensagem(mensagem.get("Body"))
        except MensagemInvalida as erro:
            log.error("mensagem malformada (%s); não apagada, vai para a DLQ após 3 recebimentos", erro)
            return

        # Daqui em diante todo log (inclusive do processador) leva pedido_id e conversa_id.
        with contexto_log(pedido_id=pedido_id, conversa_id=conversa_id):
            _processar_e_apagar(sqs, fila_url, processador, mensagem, pedido_id)


def _processar_e_apagar(sqs, fila_url, processador, mensagem, pedido_id):
    try:
        resultado = processador.processar(pedido_id)
    except PedidoInexistente:
        log.error("pedido não existe; mensagem não apagada, vai para a DLQ após 3 recebimentos")
        return
    except Exception:
        log.exception("erro inesperado; mensagem volta para a fila")
        return

    try:
        sqs.delete_message(QueueUrl=fila_url, ReceiptHandle=mensagem["ReceiptHandle"])
    except Exception:
        # O resultado já está gravado; se a mensagem voltar, será tratada como duplicada.
        log.exception("resultado %s gravado, mas falhou ao apagar a mensagem", resultado,
                      extra={"resultado": resultado})
        return

    log.info("resultado %s; mensagem apagada", resultado, extra={"resultado": resultado})


def main():
    try:
        config = carregar_config()
    except ErroDeConfiguracao as erro:
        sys.exit(f"configuração inválida: {erro}")

    # Um JSON por linha no stdout (formato em docs/contratos.md).
    configurar_logs("order-worker", config.log_level)

    signal.signal(signal.SIGTERM, pedir_parada)
    signal.signal(signal.SIGINT, pedir_parada)

    sqs = criar_cliente("sqs", config.regiao, config.sqs_endpoint_url)
    dynamodb = criar_cliente("dynamodb", config.regiao, config.dynamodb_endpoint_url)
    processador = Processador(dynamodb, config.tabela_pedidos, config.tabela_produtos)

    log.info("worker iniciado; lendo a fila", extra={"fila": config.fila_pedidos_url})

    while not parar.is_set():
        gravar_heartbeat()  # também com a fila vazia: prova que o loop está vivo

        try:
            resposta = sqs.receive_message(
                QueueUrl=config.fila_pedidos_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=20,  # long polling
                AttributeNames=["ApproximateReceiveCount"],
            )
        except Exception:
            log.exception("falha ao ler a fila; nova tentativa em 5 s")
            parar.wait(5)
            continue

        for mensagem in resposta.get("Messages", []):
            if parar.is_set():
                # As mensagens não processadas voltam à fila quando o visibility timeout vencer.
                break
            tratar_mensagem(sqs, config.fila_pedidos_url, processador, mensagem)
            gravar_heartbeat()

    log.info("worker encerrado")


if __name__ == "__main__":
    main()
