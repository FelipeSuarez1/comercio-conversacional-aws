"""Apoio dos testes: um DynamoDB falso em memória.

O fake entende só as expressões que o processador.py usa (baixa de estoque e troca
de status do pedido) e responde com os mesmos erros que o boto3 levantaria.
"""

import os
import sys

import pytest
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

# Permite "import processador" e "import worker" a partir da pasta do serviço.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TABELA_PEDIDOS = "pedidos"
TABELA_PRODUTOS = "produtos"

_serializador = TypeSerializer()


def _erro(codigo, operacao, **extras):
    resposta = {"Error": {"Code": codigo, "Message": codigo}, **extras}
    return ClientError(resposta, operacao)


class FakeDynamoDB:
    def __init__(self):
        self.produtos = {}
        self.pedidos = {}
        self.transacoes = 0
        # Função chamada antes de cada transação; serve para simular outro worker.
        self.antes_da_transacao = None
        # Se definido, a transação é cancelada com estes motivos (ex.: TransactionConflict).
        self.forcar_motivos = None

    def _tabela(self, nome):
        return {TABELA_PEDIDOS: self.pedidos, TABELA_PRODUTOS: self.produtos}[nome]

    def get_item(self, TableName, Key, ConsistentRead=False):
        chave = next(iter(Key.values()))["S"]
        item = self._tabela(TableName).get(chave)
        if item is None:
            return {}
        return {"Item": {k: _serializador.serialize(v) for k, v in item.items()}}

    def transact_write_items(self, TransactItems):
        self.transacoes += 1
        if self.antes_da_transacao:
            self.antes_da_transacao()

        motivos = []
        for operacao in TransactItems:
            update = operacao["Update"]
            motivos.append("None" if self._condicao_ok(update) else "ConditionalCheckFailed")
        if self.forcar_motivos:
            motivos = self.forcar_motivos

        if any(m != "None" for m in motivos):
            raise _erro(
                "TransactionCanceledException",
                "TransactWriteItems",
                CancellationReasons=[{"Code": m} for m in motivos],
            )

        for operacao in TransactItems:
            self._aplicar(operacao["Update"])
        return {}

    def update_item(self, **update):
        if not self._condicao_ok(update):
            raise _erro("ConditionalCheckFailedException", "UpdateItem")
        self._aplicar(update)
        return {}

    def _condicao_ok(self, update):
        tabela = update["TableName"]
        chave = next(iter(update["Key"].values()))["S"]
        valores = update["ExpressionAttributeValues"]
        item = self._tabela(tabela).get(chave)
        if item is None:
            return False
        if tabela == TABELA_PRODUTOS:
            return item.get("estoque", 0) >= int(valores[":qtd"]["N"])
        return item.get("status") == valores[":pendente"]["S"]

    def _aplicar(self, update):
        tabela = update["TableName"]
        chave = next(iter(update["Key"].values()))["S"]
        valores = update["ExpressionAttributeValues"]
        item = self._tabela(tabela)[chave]
        if tabela == TABELA_PRODUTOS:
            item["estoque"] -= int(valores[":qtd"]["N"])
            return
        novo_status = valores.get(":confirmado") or valores.get(":rejeitado")
        item["status"] = novo_status["S"]
        item["atualizado_em"] = valores[":agora"]["S"]
        if ":motivo" in valores:
            item["motivo"] = valores[":motivo"]["S"]


@pytest.fixture
def banco():
    fake = FakeDynamoDB()
    fake.produtos = {
        "etiopia-yirgacheffe": {"produto_id": "etiopia-yirgacheffe", "estoque": 10},
        "brasil-cerrado": {"produto_id": "brasil-cerrado", "estoque": 2},
    }
    return fake


@pytest.fixture
def criar_pedido(banco):
    """Grava um pedido no banco falso. itens = [(produto_id, quantidade), ...]."""

    def criar(pedido_id, itens, status="PENDENTE"):
        banco.pedidos[pedido_id] = {
            "pedido_id": pedido_id,
            "conversa_id": "conversa-1",
            "itens": [
                {"produto_id": p, "nome": p, "quantidade": q, "preco_unitario_centavos": 5000}
                for p, q in itens
            ],
            "desconto_centavos": 0,
            "total_centavos": 0,
            "status": status,
            "criado_em": "2026-01-01T00:00:00+00:00",
            "atualizado_em": "2026-01-01T00:00:00+00:00",
        }

    return criar
