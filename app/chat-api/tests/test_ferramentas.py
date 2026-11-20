"""Ferramentas do vendedor, com foco em consultar_estoque e consultar_pedido."""

import json

import ferramentas


def test_definicoes_expoem_as_quatro_ferramentas():
    nomes = {d["function"]["name"] for d in ferramentas.DEFINICOES}
    assert nomes == {"buscar_produtos", "criar_pedido", "consultar_estoque", "consultar_pedido"}
    assert nomes == set(ferramentas.FERRAMENTAS)


# ---------- consultar_estoque ----------

def test_estoque_por_produto_id(ctx):
    resultado = ferramentas.executar("consultar_estoque", {"produto_id": "panama-geisha"}, ctx)

    assert resultado == {
        "produto_id": "panama-geisha",
        "nome": "Panamá Geisha",
        "estoque": 2,
        "disponivel": True,
        "preco_reais": "R$ 189,00",
    }


def test_estoque_por_nome_sem_acento(ctx):
    resultado = ferramentas.executar("consultar_estoque", {"nome": "etiopia"}, ctx)

    assert resultado["produto_id"] == "etiopia-yirgacheffe"
    assert resultado["estoque"] == 20


def test_estoque_id_errado_cai_na_busca_por_nome(ctx):
    # Argumentos chegam como texto JSON, como o modelo manda.
    resultado = ferramentas.executar("consultar_estoque", json.dumps({"produto_id": "geisha"}), ctx)

    assert resultado["produto_id"] == "panama-geisha"


def test_estoque_zerado_indisponivel(ctx):
    resultado = ferramentas.executar("consultar_estoque", {"nome": "Quênia Nyeri"}, ctx)

    assert resultado["estoque"] == 0
    assert resultado["disponivel"] is False


def test_estoque_produto_inexistente_devolve_erro(ctx):
    resultado = ferramentas.executar("consultar_estoque", {"nome": "robusta vietnamita"}, ctx)

    assert "erro" in resultado


def test_estoque_sem_argumentos_devolve_erro(ctx):
    assert "erro" in ferramentas.executar("consultar_estoque", {}, ctx)


# ---------- consultar_pedido ----------

def test_consultar_pedido_recem_criado(ctx, repo):
    criado = ferramentas.executar(
        "criar_pedido", {"itens": [{"produto_id": "brasil-cerrado-mineiro", "quantidade": 3}]}, ctx
    )

    resultado = ferramentas.executar("consultar_pedido", {"pedido_id": criado["pedido_id"]}, ctx)

    assert resultado["pedido_id"] == criado["pedido_id"]
    assert resultado["status"] == "PENDENTE"
    assert resultado["itens"] == [{
        "produto_id": "brasil-cerrado-mineiro",
        "nome": "Cerrado Mineiro",
        "quantidade": 3,
        "preco_unitario_reais": "R$ 49,90",
    }]
    # 3 x 49,90 = 149,70; 10% de desconto = 14,97
    assert resultado["desconto_reais"] == "R$ 14,97"
    assert resultado["total_reais"] == "R$ 134,73"
    assert "motivo" not in resultado


def test_consultar_pedido_rejeitado_mostra_motivo(ctx, repo):
    repo.pedidos["p-rej"] = {
        "pedido_id": "p-rej", "conversa_id": "c", "status": "REJEITADO",
        "motivo": "estoque insuficiente", "itens": [], "desconto_centavos": 0,
        "total_centavos": 0, "criado_em": "x", "atualizado_em": "y",
    }

    resultado = ferramentas.executar("consultar_pedido", {"pedido_id": "p-rej"}, ctx)

    assert resultado["status"] == "REJEITADO"
    assert resultado["motivo"] == "estoque insuficiente"


def test_consultar_pedido_inexistente_ou_sem_id(ctx):
    assert "erro" in ferramentas.executar("consultar_pedido", {"pedido_id": "nao-existe"}, ctx)
    assert "erro" in ferramentas.executar("consultar_pedido", {}, ctx)


# ---------- criar_pedido continua igual, agora com conversa_id na fila ----------

def test_criar_pedido_envia_conversa_id_na_fila(ctx, repo):
    criado = ferramentas.executar(
        "criar_pedido", {"itens": [{"produto_id": "panama-geisha", "quantidade": 1}]}, ctx
    )

    assert json.loads(repo.fila[0]) == {"pedido_id": criado["pedido_id"], "conversa_id": "conversa-teste"}
    assert ctx.pedidos_criados == [criado["pedido_id"]]
