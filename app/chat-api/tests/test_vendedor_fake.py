"""Modo LLM fake: roteamento por palavras-chave para as quatro ferramentas."""

from vendedor import responder_fake


def test_compra_continua_criando_pedido(ctx, repo):
    texto = responder_fake("quero 2 pacotes de Cerrado Mineiro", ctx)

    assert len(ctx.pedidos_criados) == 1
    assert ctx.pedidos_criados[0] in texto
    assert repo.pedidos[ctx.pedidos_criados[0]]["itens"][0]["quantidade"] == 2


def test_busca_continua_listando(ctx):
    texto = responder_fake("algo frutado", ctx)

    assert texto.startswith("Encontrei estes cafés:")
    assert "Etiópia Yirgacheffe" in texto


def test_pergunta_de_estoque_usa_consultar_estoque(ctx):
    texto = responder_fake("Tem estoque do Geisha?", ctx)

    assert texto == "Temos 2 pacotes de Panamá Geisha em estoque (R$ 189,00 cada)."
    assert ctx.pedidos_criados == []


def test_estoque_zerado(ctx):
    assert "sem estoque" in responder_fake("o quenia esta disponivel?", ctx)


def test_pedido_pelo_id_na_mensagem(ctx):
    responder_fake("quero 1 pacote de Geisha", ctx)
    pedido_id = ctx.pedidos_criados[0]

    texto = responder_fake(f"status do {pedido_id.upper()}", ctx)

    assert texto.startswith(f"Pedido {pedido_id}: PENDENTE.")
    assert "1x Panamá Geisha" in texto
    assert len(ctx.pedidos_criados) == 1  # o id (com dígitos) não virou quantidade


def test_e_o_meu_pedido_usa_id_do_historico(ctx, repo):
    resposta_compra = responder_fake("quero 3 pacotes de Cerrado Mineiro", ctx)
    pedido_id = ctx.pedidos_criados[0]
    repo.pedidos[pedido_id]["status"] = "CONFIRMADO"
    historico = [
        {"papel": "cliente", "conteudo": "quero 3 pacotes de Cerrado Mineiro"},
        {"papel": "vendedor", "conteudo": resposta_compra},
    ]

    texto = responder_fake("E o meu pedido?", ctx, historico)

    assert texto.startswith(f"Pedido {pedido_id}: CONFIRMADO.")


def test_e_o_meu_pedido_sem_historico_pede_o_numero(ctx):
    assert "número" in responder_fake("e o meu pedido?", ctx, [])
