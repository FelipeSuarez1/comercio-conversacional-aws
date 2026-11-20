"""Logs JSON do worker: correlação por pedido_id / conversa_id e nível ERROR."""

import io
import json
import logging

import pytest

from conftest import TABELA_PEDIDOS, TABELA_PRODUTOS
from log_json import FormatadorJSON
from processador import Processador, extrair_mensagem
from worker import tratar_mensagem

FILA = "http://sqs:9324/000000000000/pedidos"


class FakeSQS:
    def delete_message(self, QueueUrl, ReceiptHandle):
        pass


@pytest.fixture
def logs_json():
    saida = io.StringIO()
    handler = logging.StreamHandler(saida)
    handler.setFormatter(FormatadorJSON("order-worker"))
    raiz = logging.getLogger()
    nivel_antigo = raiz.level
    raiz.addHandler(handler)
    raiz.setLevel(logging.INFO)

    def linhas():
        return [linha for linha in saida.getvalue().splitlines() if linha.strip()]

    yield linhas
    raiz.removeHandler(handler)
    raiz.setLevel(nivel_antigo)


def _tratar(banco, corpo):
    processador = Processador(banco, TABELA_PEDIDOS, TABELA_PRODUTOS)
    mensagem = {"MessageId": "m1", "ReceiptHandle": "r1", "Body": corpo,
                "Attributes": {"ApproximateReceiveCount": "1"}}
    tratar_mensagem(FakeSQS(), FILA, processador, mensagem)


def test_extrair_mensagem_com_e_sem_conversa_id():
    assert extrair_mensagem('{"pedido_id": "p1", "conversa_id": "c1"}') == ("p1", "c1")
    # Mensagens antigas (e dos scripts de carga) só têm o pedido_id.
    assert extrair_mensagem('{"pedido_id": "p1"}') == ("p1", None)
    assert extrair_mensagem('{"pedido_id": "p1", "conversa_id": ""}') == ("p1", None)


def test_confirmacao_loga_pedido_e_conversa(banco, criar_pedido, logs_json):
    criar_pedido("p1", [("etiopia-yirgacheffe", 1)])

    _tratar(banco, json.dumps({"pedido_id": "p1", "conversa_id": "conversa-1"}))

    eventos = [json.loads(linha) for linha in logs_json()]
    assert {e["mensagem"] for e in eventos} >= {
        "pedido confirmado; estoque baixado", "resultado CONFIRMADO; mensagem apagada",
    }
    for evento in eventos:
        assert evento["servico"] == "order-worker"
        assert evento["nivel"] == "INFO"
        assert evento["pedido_id"] == "p1"
        assert evento["conversa_id"] == "conversa-1"
        assert evento["message_id"] == "m1"


def test_mensagem_sem_conversa_id_usa_a_do_pedido(banco, criar_pedido, logs_json):
    criar_pedido("p2", [("etiopia-yirgacheffe", 1)])

    _tratar(banco, json.dumps({"pedido_id": "p2"}))

    eventos = [json.loads(linha) for linha in logs_json()]
    confirmado = next(e for e in eventos if e["mensagem"].startswith("pedido confirmado"))
    assert confirmado["conversa_id"] == "conversa-1"  # lido do pedido no DynamoDB


@pytest.mark.parametrize("corpo", ["{quebrado", json.dumps({"pedido_id": "nao-existe"})])
def test_erros_saem_em_nivel_error(banco, corpo, logs_json):
    _tratar(banco, corpo)

    linhas = logs_json()
    assert len(linhas) == 1
    evento = json.loads(linhas[0])
    assert evento["nivel"] == "ERROR"
    # O metric filter do CloudWatch (pattern "ERROR") casa com o termo na linha crua.
    assert '"nivel": "ERROR"' in linhas[0]


def test_erro_inesperado_tem_traceback_numa_linha(banco, criar_pedido, logs_json):
    criar_pedido("p3", [("etiopia-yirgacheffe", 1)])
    banco.forcar_motivos = ["TransactionConflict", "None"]

    _tratar(banco, json.dumps({"pedido_id": "p3"}))

    evento = json.loads(logs_json()[-1])
    assert evento["nivel"] == "ERROR"
    assert evento["pedido_id"] == "p3"
    assert "TransactionCanceledException" in evento["excecao"]
