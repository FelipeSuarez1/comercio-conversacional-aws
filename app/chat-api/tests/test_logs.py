"""Formato dos logs (um JSON por linha) e correlação por conversa_id / pedido_id."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

import ferramentas
from log_json import contexto_log


def test_formato_basico_e_nivel_error(logs_json):
    log = logging.getLogger("teste")
    log.info("tudo certo", extra={"pedido_id": "p1"})
    try:
        raise RuntimeError("falhou")
    except RuntimeError:
        log.exception("deu ruim")

    info, erro = [json.loads(linha) for linha in logs_json()]
    for campo in ("timestamp", "nivel", "servico", "logger", "mensagem"):
        assert campo in info
    assert info["nivel"] == "INFO"
    assert info["servico"] == "chat-api"
    assert info["mensagem"] == "tudo certo"
    assert info["pedido_id"] == "p1"
    assert info["timestamp"].endswith("Z")

    # O metric filter do CloudWatch procura o termo ERROR na linha.
    assert erro["nivel"] == "ERROR"
    assert "ERROR" in logs_json()[1]
    assert "RuntimeError: falhou" in erro["excecao"]
    assert "\n" not in logs_json()[1]  # traceback dentro do JSON, numa linha só


def test_contexto_vale_dentro_do_bloco(logs_json):
    log = logging.getLogger("teste")
    with contexto_log(conversa_id="c1", ignorado=None):
        log.info("dentro")
    log.info("fora")

    dentro, fora = [json.loads(linha) for linha in logs_json()]
    assert dentro["conversa_id"] == "c1"
    assert "ignorado" not in dentro
    assert "conversa_id" not in fora


def test_criar_pedido_loga_ids(ctx, logs_json):
    criado = ferramentas.executar(
        "criar_pedido", {"itens": [{"produto_id": "panama-geisha", "quantidade": 1}]}, ctx
    )

    eventos = [json.loads(linha) for linha in logs_json()]
    enviados = [e for e in eventos if e["mensagem"] == "pedido enviado para a fila"]
    assert enviados and enviados[0]["pedido_id"] == criado["pedido_id"]
    assert enviados[0]["conversa_id"] == "conversa-teste"


@pytest.fixture
def cliente(repo, monkeypatch):
    import main
    monkeypatch.setattr(main, "repo", repo)
    monkeypatch.setattr(main.vendedor, "repo", repo)
    return TestClient(main.app)


def test_chat_correlaciona_request_e_conversa(cliente, repo, logs_json):
    resposta = cliente.post("/chat", json={"conversa_id": "conv-42", "mensagem": "quero 2 pacotes de Geisha"},
                            headers={"X-Request-Id": "req-1"})

    assert resposta.status_code == 200
    assert resposta.headers["X-Request-Id"] == "req-1"
    pedido_id = resposta.json()["pedidos_criados"][0]

    eventos = [json.loads(linha) for linha in logs_json()]
    da_rota = [e for e in eventos if e["logger"] in ("chat-api", "ferramentas", "vendedor")]
    # Todos os logs feitos durante a requisição levam request_id e conversa_id.
    for evento in da_rota:
        assert evento["request_id"] == "req-1"
        assert evento["conversa_id"] == "conv-42"
    assert any(e.get("pedido_id") == pedido_id for e in da_rota)
    assert json.loads(repo.fila[0])["conversa_id"] == "conv-42"


def test_chat_e_o_meu_pedido(cliente, repo):
    compra = cliente.post("/chat", json={"conversa_id": "conv-7", "mensagem": "quero 1 pacote de Geisha"})
    pedido_id = compra.json()["pedidos_criados"][0]

    resposta = cliente.post("/chat", json={"conversa_id": "conv-7", "mensagem": "e o meu pedido?"})

    assert resposta.status_code == 200
    assert resposta.json()["resposta"].startswith(f"Pedido {pedido_id}: PENDENTE.")
    assert resposta.json()["pedidos_criados"] == []
