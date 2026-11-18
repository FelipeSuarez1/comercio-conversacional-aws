import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from conftest import TABELA_PEDIDOS, TABELA_PRODUTOS
from processador import (
    CONFIRMADO,
    DUPLICADO,
    MOTIVO_SEM_ESTOQUE,
    REJEITADO,
    MensagemInvalida,
    PedidoInexistente,
    Processador,
    extrair_pedido_id,
)

AGORA = "2026-11-18T12:00:00+00:00"


@pytest.fixture
def processador(banco):
    return Processador(banco, TABELA_PEDIDOS, TABELA_PRODUTOS, relogio=lambda: AGORA)


def test_confirma_e_baixa_estoque(banco, criar_pedido, processador):
    criar_pedido("p1", [("etiopia-yirgacheffe", 3), ("brasil-cerrado", 2)])

    assert processador.processar("p1") == CONFIRMADO

    assert banco.pedidos["p1"]["status"] == CONFIRMADO
    assert banco.pedidos["p1"]["atualizado_em"] == AGORA
    assert banco.produtos["etiopia-yirgacheffe"]["estoque"] == 7
    assert banco.produtos["brasil-cerrado"]["estoque"] == 0


def test_estoque_insuficiente_rejeita_sem_mexer_no_estoque(banco, criar_pedido, processador):
    criar_pedido("p2", [("etiopia-yirgacheffe", 1), ("brasil-cerrado", 3)])

    assert processador.processar("p2") == REJEITADO

    assert banco.pedidos["p2"]["status"] == REJEITADO
    assert banco.pedidos["p2"]["motivo"] == MOTIVO_SEM_ESTOQUE
    assert banco.pedidos["p2"]["atualizado_em"] == AGORA
    # Transação é tudo ou nada: o item que tinha estoque também não foi baixado.
    assert banco.produtos["etiopia-yirgacheffe"]["estoque"] == 10
    assert banco.produtos["brasil-cerrado"]["estoque"] == 2


def test_produto_inexistente_rejeita(banco, criar_pedido, processador):
    criar_pedido("p3", [("produto-que-nao-existe", 1)])

    assert processador.processar("p3") == REJEITADO
    assert banco.pedidos["p3"]["motivo"] == MOTIVO_SEM_ESTOQUE


def test_pedido_ja_processado_e_duplicado(banco, criar_pedido, processador):
    criar_pedido("p4", [("etiopia-yirgacheffe", 1)], status=CONFIRMADO)

    assert processador.processar("p4") == DUPLICADO

    assert banco.transacoes == 0
    assert banco.produtos["etiopia-yirgacheffe"]["estoque"] == 10


def test_outro_worker_confirmou_no_meio_e_duplicado(banco, criar_pedido, processador):
    criar_pedido("p5", [("etiopia-yirgacheffe", 1)])

    def outro_worker():
        banco.pedidos["p5"]["status"] = CONFIRMADO

    banco.antes_da_transacao = outro_worker

    assert processador.processar("p5") == DUPLICADO
    assert banco.produtos["etiopia-yirgacheffe"]["estoque"] == 10


def test_outro_worker_no_meio_e_sem_estoque_e_duplicado(banco, criar_pedido, processador):
    # Condição do pedido e do estoque falham juntas: vale a do pedido (não rejeita de novo).
    criar_pedido("p6", [("brasil-cerrado", 5)])

    def outro_worker():
        banco.pedidos["p6"]["status"] = REJEITADO

    banco.antes_da_transacao = outro_worker

    assert processador.processar("p6") == DUPLICADO
    assert "motivo" not in banco.pedidos["p6"]


def test_pedido_inexistente_levanta_erro(processador):
    with pytest.raises(PedidoInexistente):
        processador.processar("nao-existe")


def test_mesmo_produto_repetido_soma_quantidades(banco, criar_pedido, processador):
    criar_pedido("p7", [("etiopia-yirgacheffe", 4), ("etiopia-yirgacheffe", 4)])

    assert processador.processar("p7") == CONFIRMADO
    assert banco.produtos["etiopia-yirgacheffe"]["estoque"] == 2


def test_conflito_de_transacao_propaga_erro(banco, criar_pedido, processador):
    # Cancelamento que não é por condição: não decide nada, a mensagem volta à fila.
    criar_pedido("p8", [("etiopia-yirgacheffe", 1)])
    banco.forcar_motivos = ["TransactionConflict", "None"]

    with pytest.raises(ClientError):
        processador.processar("p8")
    assert banco.pedidos["p8"]["status"] == "PENDENTE"


@pytest.mark.parametrize(
    "corpo",
    ["isto não é json", "[]", "{}", '{"pedido_id": ""}', '{"pedido_id": 123}', None],
)
def test_mensagem_malformada(corpo):
    with pytest.raises(MensagemInvalida):
        extrair_pedido_id(corpo)


def test_extrai_pedido_id():
    assert extrair_pedido_id('{"pedido_id": "abc-123"}') == "abc-123"


def test_requisicoes_validas_para_o_boto3():
    """Usa um cliente boto3 de verdade (sem rede) para validar o formato das chamadas."""
    cliente = boto3.client(
        "dynamodb",
        region_name="us-east-1",
        aws_access_key_id="teste",
        aws_secret_access_key="teste",
    )
    pedido = {
        "pedido_id": {"S": "p9"},
        "status": {"S": "PENDENTE"},
        "itens": {"L": [{"M": {"produto_id": {"S": "etiopia-yirgacheffe"}, "quantidade": {"N": "2"}}}]},
    }
    with Stubber(cliente) as stub:
        stub.add_response("get_item", {"Item": pedido})
        stub.add_response("transact_write_items", {})
        assert Processador(cliente, TABELA_PEDIDOS, TABELA_PRODUTOS).processar("p9") == CONFIRMADO
        stub.assert_no_pending_responses()

    with Stubber(cliente) as stub:
        stub.add_response("get_item", {"Item": pedido})
        stub.add_client_error(
            "transact_write_items",
            service_error_code="TransactionCanceledException",
            modeled_fields={"CancellationReasons": [{"Code": "ConditionalCheckFailed"}, {"Code": "None"}]},
        )
        stub.add_response("update_item", {})
        assert Processador(cliente, TABELA_PEDIDOS, TABELA_PRODUTOS).processar("p9") == REJEITADO
        stub.assert_no_pending_responses()
