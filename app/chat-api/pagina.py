"""Página web do vendedor: chat + catálogo com estoque ao vivo.

HTML estático servido em GET /. Fala só com as rotas da própria API
(/chat, /produtos, /pedidos/{id}); não tem dependências externas.
"""

HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Grão — vendedor de cafés especiais</title>
<style>
  :root {
    --fundo: #f6f1ea; --cartao: #ffffff; --texto: #2a211b; --suave: #6b5d52;
    --destaque: #8a4b14; --borda: #e2d6c8; --ok: #1f7a3a; --erro: #a12d2d; --pend: #8a6a14;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; font-size: 18px;
         background: var(--fundo); color: var(--texto); }
  header { padding: 16px 24px; background: var(--destaque); color: #fff; }
  header h1 { margin: 0; font-size: 26px; }
  header p { margin: 4px 0 0; font-size: 16px; opacity: .9; }
  main { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 20px;
         padding: 20px 24px; height: calc(100vh - 92px); }
  section { background: var(--cartao); border: 1px solid var(--borda); border-radius: 12px;
            display: flex; flex-direction: column; min-height: 0; }
  section h2 { margin: 0; padding: 14px 18px; font-size: 20px; border-bottom: 1px solid var(--borda); }
  #mensagens { flex: 1; overflow-y: auto; padding: 18px; display: flex; flex-direction: column; gap: 12px; }
  .msg { max-width: 85%; padding: 12px 16px; border-radius: 12px; line-height: 1.45; white-space: pre-wrap; }
  .cliente { align-self: flex-end; background: #f0dfcb; }
  .vendedor { align-self: flex-start; background: #f4f4f4; }
  .aviso { align-self: center; color: var(--suave); font-size: 16px; }
  .pedido { align-self: flex-start; border: 2px solid var(--destaque); border-radius: 12px;
            padding: 12px 16px; background: #fffaf3; max-width: 85%; }
  .pedido b { color: var(--destaque); }
  .status { font-weight: 700; }
  .CONFIRMADO { color: var(--ok); } .REJEITADO { color: var(--erro); } .PENDENTE { color: var(--pend); }
  form { display: flex; gap: 10px; padding: 14px; border-top: 1px solid var(--borda); }
  input { flex: 1; font-size: 18px; padding: 12px 14px; border: 1px solid var(--borda); border-radius: 10px; }
  button { font-size: 18px; padding: 12px 20px; border: 0; border-radius: 10px;
           background: var(--destaque); color: #fff; cursor: pointer; }
  button:disabled { opacity: .5; cursor: wait; }
  #catalogo { flex: 1; overflow-y: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 17px; }
  th, td { padding: 9px 14px; text-align: left; border-bottom: 1px solid var(--borda); }
  th { color: var(--suave); font-weight: 600; position: sticky; top: 0; background: var(--cartao); }
  td.num { text-align: right; white-space: nowrap; }
  tr.mudou td { background: #fdeccd; transition: background 1s; }
  .rodape { padding: 10px 16px; font-size: 15px; color: var(--suave); border-top: 1px solid var(--borda); }
  @media (max-width: 800px) { main { grid-template-columns: 1fr; height: auto; }
                              #mensagens { min-height: 50vh; } }
</style>
</head>
<body>
<header>
  <h1>Grão — vendedor de cafés especiais</h1>
  <p>Converse em linguagem natural: peça recomendações, pergunte o estoque e feche o pedido.</p>
</header>
<main>
  <section>
    <h2>Conversa</h2>
    <div id="mensagens">
      <div class="aviso">Exemplo: "Quero um café frutado para coado, o que vocês têm?"</div>
    </div>
    <form id="form">
      <input id="entrada" autocomplete="off" placeholder="Escreva sua mensagem..." maxlength="2000" required>
      <button id="enviar" type="submit">Enviar</button>
    </form>
  </section>
  <section>
    <h2>Catálogo e estoque (ao vivo)</h2>
    <div id="catalogo">
      <table>
        <thead><tr><th>Café</th><th class="num">Preço</th><th class="num">Estoque</th></tr></thead>
        <tbody id="produtos"></tbody>
      </table>
    </div>
    <div class="rodape">Dados lidos do DynamoDB a cada 3 s. Atendido pela task: <span id="task">—</span></div>
  </section>
</main>
<script>
  const reais = c => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  const mensagens = document.getElementById("mensagens");
  const estoqueAnterior = {};
  let conversaId = null;

  function adicionar(classe, texto) {
    const div = document.createElement("div");
    div.className = "msg " + classe;
    div.textContent = texto;
    mensagens.appendChild(div);
    mensagens.scrollTop = mensagens.scrollHeight;
    return div;
  }

  // Markdown mínimo da resposta da IA (negrito e listas), com o texto escapado antes:
  // nada vindo da IA vira HTML a não ser as tags geradas aqui.
  function adicionarFormatado(texto) {
    const escapar = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    const html = escapar(texto)
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/^\s*[-*] /gm, "• ")
      .replace(/^#+\s*/gm, "");
    const div = adicionar("vendedor", "");
    div.innerHTML = html;
    mensagens.scrollTop = mensagens.scrollHeight;
  }

  async function atualizarCatalogo() {
    try {
      const r = await fetch("/produtos");
      const produtos = await r.json();
      const corpo = document.getElementById("produtos");
      corpo.replaceChildren();
      for (const p of produtos) {
        const tr = document.createElement("tr");
        const mudou = p.produto_id in estoqueAnterior && estoqueAnterior[p.produto_id] !== p.estoque;
        if (mudou) tr.className = "mudou";
        estoqueAnterior[p.produto_id] = p.estoque;
        for (const [valor, classe] of [[p.nome, ""], [reais(p.preco_centavos), "num"], [String(p.estoque), "num"]]) {
          const td = document.createElement("td");
          td.textContent = valor;
          if (classe) td.className = classe;
          tr.appendChild(td);
        }
        corpo.appendChild(tr);
      }
    } catch (e) { /* tenta de novo no próximo ciclo */ }
  }

  function acompanharPedido(id) {
    const card = document.createElement("div");
    card.className = "pedido";
    mensagens.appendChild(card);
    const desenhar = p => {
      card.replaceChildren();
      const titulo = document.createElement("div");
      titulo.innerHTML = "<b>Pedido registrado</b> ";
      const st = document.createElement("span");
      st.className = "status " + p.status;
      st.textContent = p.status;
      titulo.appendChild(st);
      card.appendChild(titulo);
      const linhas = [
        "ID: " + p.pedido_id,
        ...p.itens.map(i => i.quantidade + "x " + i.nome + " — " + reais(i.preco_unitario_centavos)),
        (p.desconto_centavos ? "Desconto: " + reais(p.desconto_centavos) + " · " : "") + "Total: " + reais(p.total_centavos),
      ];
      if (p.motivo) linhas.push("Motivo: " + p.motivo);
      for (const l of linhas) { const d = document.createElement("div"); d.textContent = l; card.appendChild(d); }
      mensagens.scrollTop = mensagens.scrollHeight;
    };
    const consultar = async (tentativa) => {
      try {
        const r = await fetch("/pedidos/" + encodeURIComponent(id));
        if (r.ok) {
          const p = await r.json();
          desenhar(p);
          if (p.status !== "PENDENTE") { atualizarCatalogo(); return; }
        }
      } catch (e) {}
      if (tentativa < 30) setTimeout(() => consultar(tentativa + 1), 2000);
    };
    consultar(0);
  }

  document.getElementById("form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const entrada = document.getElementById("entrada");
    const botao = document.getElementById("enviar");
    const texto = entrada.value.trim();
    if (!texto) return;
    adicionar("cliente", texto);
    entrada.value = "";
    botao.disabled = true;
    const pensando = adicionar("aviso", "O vendedor está consultando o catálogo...");
    try {
      const r = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversa_id: conversaId, mensagem: texto }),
      });
      document.getElementById("task").textContent = r.headers.get("x-task") || "—";
      const dados = await r.json();
      pensando.remove();
      if (!r.ok) { adicionar("aviso", dados.detail || "Erro ao falar com o vendedor."); return; }
      conversaId = dados.conversa_id;
      adicionarFormatado(dados.resposta);
      for (const id of dados.pedidos_criados) acompanharPedido(id);
    } catch (e) {
      pensando.remove();
      adicionar("aviso", "Falha de rede. Tente de novo.");
    } finally {
      botao.disabled = false;
      entrada.focus();
    }
  });

  atualizarCatalogo();
  setInterval(atualizarCatalogo, 3000);
</script>
</body>
</html>
"""
