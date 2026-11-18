"""Confere quando o worker apaga (ou não) a mensagem da fila."""

import json

import pytest

from conftest import TABELA_PEDIDOS, TABELA_PRODUTOS
from processador import Processador
from worker import tratar_mensagem

FILA = "http://sqs:9324/000000000000/pedidos"


class FakeSQS:
    def __init__(self):
        self.apagadas = []

    def delete_message(self, QueueUrl, ReceiptHandle):
        self.apagadas.append(ReceiptHandle)


@pytest.fixture
def sqs():
    return FakeSQS()


@pytest.fixture
def processador(banco):
    return Processador(banco, TABELA_PEDIDOS, TABELA_PRODUTOS)


def mensagem(corpo):
    return {"MessageId": "m1", "ReceiptHandle": "recibo-1", "Body": corpo}


def test_apaga_depois_de_confirmar(sqs, processador, banco, criar_pedido):
    criar_pedido("p1", [("etiopia-yirgacheffe", 1)])

    tratar_mensagem(sqs, FILA, processador, mensagem(json.dumps({"pedido_id": "p1"})))

    assert banco.pedidos["p1"]["status"] == "CONFIRMADO"
    assert sqs.apagadas == ["recibo-1"]


def test_apaga_duplicada(sqs, processador, criar_pedido):
    criar_pedido("p2", [("etiopia-yirgacheffe", 1)], status="REJEITADO")

    tratar_mensagem(sqs, FILA, processador, mensagem(json.dumps({"pedido_id": "p2"})))

    assert sqs.apagadas == ["recibo-1"]


@pytest.mark.parametrize("corpo", ["{quebrado", json.dumps({"outro": 1}), json.dumps({"pedido_id": "nao-existe"})])
def test_nao_apaga_malformada_nem_inexistente(sqs, processador, corpo):
    tratar_mensagem(sqs, FILA, processador, mensagem(corpo))

    assert sqs.apagadas == []


def test_nao_apaga_em_erro_inesperado(sqs, processador, banco, criar_pedido):
    criar_pedido("p3", [("etiopia-yirgacheffe", 1)])
    banco.forcar_motivos = ["TransactionConflict", "None"]

    tratar_mensagem(sqs, FILA, processador, mensagem(json.dumps({"pedido_id": "p3"})))

    assert sqs.apagadas == []
