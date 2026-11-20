"""Apoio dos testes do chat-api: um repositório falso em memória e captura de logs JSON."""

import io
import json
import logging
import os
import sys

import pytest

# Permite "import ferramentas", "import vendedor" etc. a partir da pasta do serviço.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# main.py lê a configuração ao ser importado; modo fake, sem chave de LLM.
for nome, valor in {
    "AWS_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "teste",
    "AWS_SECRET_ACCESS_KEY": "teste",
    "TABELA_PRODUTOS": "produtos",
    "TABELA_PEDIDOS": "pedidos",
    "TABELA_CONVERSAS": "conversas",
    "FILA_PEDIDOS_URL": "http://sqs:9324/000000000000/pedidos",
    "LLM_MODO": "fake",
}.items():
    os.environ.setdefault(nome, valor)

from log_json import FormatadorJSON  # noqa: E402


class FakeRepo:
    """Mesma interface do repositorio.Repositorio, guardando tudo em dicionários."""

    def __init__(self):
        self.produtos = {}
        self.pedidos = {}
        self.fila = []
        self.mensagens = []

    def listar_produtos(self):
        return sorted(self.produtos.values(), key=lambda p: p.get("nome", ""))

    def obter_produto(self, produto_id):
        return self.produtos.get(produto_id)

    def salvar_pedido(self, pedido):
        assert pedido["pedido_id"] not in self.pedidos
        self.pedidos[pedido["pedido_id"]] = pedido

    def obter_pedido(self, pedido_id):
        return self.pedidos.get(pedido_id)

    def enviar_para_fila(self, pedido_id, conversa_id=None):
        corpo = {"pedido_id": pedido_id}
        if conversa_id:
            corpo["conversa_id"] = conversa_id
        self.fila.append(json.dumps(corpo))

    def salvar_mensagem(self, conversa_id, papel, conteudo):
        self.mensagens.append({"conversa_id": conversa_id, "papel": papel, "conteudo": conteudo})

    def carregar_historico(self, conversa_id, limite=20):
        historico = [
            {"papel": m["papel"], "conteudo": m["conteudo"]}
            for m in self.mensagens if m["conversa_id"] == conversa_id
        ]
        return historico[-limite:]


def _produto(produto_id, nome, preco_centavos, estoque, notas):
    return {
        "produto_id": produto_id, "nome": nome, "descricao": "", "origem": "",
        "torra": "media", "notas": notas, "preco_centavos": preco_centavos, "estoque": estoque,
    }


@pytest.fixture
def repo():
    fake = FakeRepo()
    for p in (
        _produto("panama-geisha", "Panamá Geisha", 18900, 2, ["floral", "jasmim"]),
        _produto("etiopia-yirgacheffe", "Etiópia Yirgacheffe", 6990, 20, ["frutado", "citrico"]),
        _produto("brasil-cerrado-mineiro", "Cerrado Mineiro", 4990, 50, ["chocolate", "nozes"]),
        _produto("quenia-nyeri", "Quênia Nyeri", 7490, 0, ["frutas vermelhas"]),
    ):
        fake.produtos[p["produto_id"]] = p
    return fake


@pytest.fixture
def ctx(repo):
    import ferramentas
    return ferramentas.Contexto(repo=repo, conversa_id="conversa-teste")


@pytest.fixture
def logs_json():
    """Captura o que vai para o stdout no formato JSON; devolve uma função que lê as linhas."""
    saida = io.StringIO()
    handler = logging.StreamHandler(saida)
    handler.setFormatter(FormatadorJSON("chat-api"))
    raiz = logging.getLogger()
    nivel_antigo = raiz.level
    raiz.addHandler(handler)
    raiz.setLevel(logging.INFO)

    def linhas():
        return [linha for linha in saida.getvalue().splitlines() if linha.strip()]

    yield linhas
    raiz.removeHandler(handler)
    raiz.setLevel(nivel_antigo)
