"""O vendedor: conversa com o cliente usando o LLM e as ferramentas.

Dois modos (variável LLM_MODO):
- real: chama a API de chat completions e executa as tools que o modelo pedir;
- fake: regras fixas, sem API, para testes e carga. Usa as mesmas ferramentas.
"""

import json
import logging
import re
from dataclasses import dataclass, field

import openai

import ferramentas
from config import Config
from repositorio import Repositorio

log = logging.getLogger(__name__)

MAXIMO_ITERACOES = 5
TIMEOUT_LLM_SEGUNDOS = 20

PROMPT_SISTEMA = """Você é o vendedor da Grão, uma loja online de cafés especiais. \
Fale em português do Brasil, de forma simpática, breve e prestativa.

Regras:
- Só ofereça cafés que existem no catálogo. Sempre consulte a ferramenta \
buscar_produtos antes de recomendar um café ou informar preço e estoque; \
nunca invente produtos, preços ou estoques.
- Os preços são por pacote de 250 g. Há desconto de 10% no item quando o \
cliente leva 3 ou mais pacotes do mesmo café.
- Antes de chamar criar_pedido, repita para o cliente os cafés e as \
quantidades e peça a confirmação. Só crie o pedido depois que ele confirmar.
- Depois de criar o pedido, informe o número do pedido e o total, e avise que \
o pedido fica pendente até a confirmação do estoque.
- Se uma ferramenta devolver erro, explique o problema ao cliente com \
naturalidade.
- Assuntos fora da loja: responda com educação que você só pode ajudar com \
os cafés da Grão."""


class LLMIndisponivel(Exception):
    """A API do LLM falhou (timeout, rede, erro do provedor)."""


@dataclass
class Resposta:
    texto: str
    pedidos_criados: list[str] = field(default_factory=list)


class Vendedor:
    def __init__(self, config: Config, repo: Repositorio):
        self.config = config
        self.repo = repo
        self.cliente_llm = None
        if config.llm_modo == "real":
            # timeout de 20 s por chamada e 1 retentativa automática do próprio SDK
            # (em timeout, falha de rede, 429 e erros 5xx).
            self.cliente_llm = openai.OpenAI(
                api_key=config.llm_api_key,
                base_url=config.llm_base_url,
                timeout=TIMEOUT_LLM_SEGUNDOS,
                max_retries=1,
            )

    def responder(self, conversa_id: str, mensagem: str, historico: list[dict]) -> Resposta:
        ctx = ferramentas.Contexto(repo=self.repo, conversa_id=conversa_id)
        if self.config.llm_modo == "fake":
            texto = responder_fake(mensagem, ctx)
        else:
            texto = self._responder_real(mensagem, historico, ctx)
        return Resposta(texto=texto, pedidos_criados=ctx.pedidos_criados)

    # ---------- modo real ----------

    def _responder_real(self, mensagem: str, historico: list[dict],
                        ctx: ferramentas.Contexto) -> str:
        mensagens = [{"role": "system", "content": PROMPT_SISTEMA}]
        for item in historico:
            papel = "user" if item["papel"] == "cliente" else "assistant"
            mensagens.append({"role": papel, "content": item["conteudo"]})
        mensagens.append({"role": "user", "content": mensagem})

        for iteracao in range(1, MAXIMO_ITERACOES + 1):
            try:
                resposta = self.cliente_llm.chat.completions.create(
                    model=self.config.model_id,
                    messages=mensagens,
                    tools=ferramentas.DEFINICOES,
                )
                escolha = resposta.choices[0].message
            except (openai.OpenAIError, IndexError, AttributeError) as erro:
                log.error("falha na chamada ao LLM conversa_id=%s iteracao=%s erro=%s",
                          ctx.conversa_id, iteracao, type(erro).__name__)
                if ctx.pedidos_criados:
                    # O pedido já foi gravado e enviado; não dá para fingir que não existe.
                    return _texto_pedidos_registrados(ctx.pedidos_criados)
                raise LLMIndisponivel() from erro

            if not escolha.tool_calls:
                return escolha.content or "Desculpe, não consegui responder agora. Pode repetir?"

            # O modelo pediu ferramentas: registramos o pedido dele e devolvemos os resultados.
            mensagens.append({
                "role": "assistant",
                "content": escolha.content,
                "tool_calls": [
                    {
                        "id": chamada.id,
                        "type": "function",
                        "function": {
                            "name": chamada.function.name,
                            "arguments": chamada.function.arguments,
                        },
                    }
                    for chamada in escolha.tool_calls
                ],
            })
            for chamada in escolha.tool_calls:
                log.info("tool chamada conversa_id=%s tool=%s",
                         ctx.conversa_id, chamada.function.name)
                resultado = ferramentas.executar(
                    chamada.function.name, chamada.function.arguments, ctx
                )
                mensagens.append({
                    "role": "tool",
                    "tool_call_id": chamada.id,
                    "content": json.dumps(resultado, ensure_ascii=False),
                })

        log.warning("limite de iteracoes atingido conversa_id=%s", ctx.conversa_id)
        if ctx.pedidos_criados:
            return _texto_pedidos_registrados(ctx.pedidos_criados)
        return "Desculpe, me enrolei aqui. Pode reformular o que você procura?"


def _texto_pedidos_registrados(pedidos: list[str]) -> str:
    ids = ", ".join(pedidos)
    return (f"Seu pedido foi registrado (número {ids}) e está pendente até a "
            "confirmação do estoque.")


# ---------- modo fake ----------

PALAVRAS_COMPRA = ("quero", "comprar", "fecha")


def responder_fake(mensagem: str, ctx: ferramentas.Contexto) -> str:
    """Vendedor determinístico, sem LLM.

    - "quero/comprar/fecha" + um número: cria pedido do primeiro produto que casar;
    - qualquer outra coisa: busca produtos com o texto e lista o resultado.
    "até 60" ou "R$ 60" vira preço máximo, e não quantidade.
    """
    texto = ferramentas.normalizar(mensagem)

    preco_maximo = None
    achou_preco = re.search(r"(?:r\$|ate)\s*(\d+(?:[.,]\d{1,2})?)", texto)
    if achou_preco:
        preco_maximo = float(achou_preco.group(1).replace(",", "."))
        texto = texto[:achou_preco.start()] + " " + texto[achou_preco.end():]

    argumentos_busca = {"texto": texto}
    if preco_maximo is not None:
        argumentos_busca["preco_maximo_reais"] = preco_maximo
    busca = ferramentas.executar("buscar_produtos", argumentos_busca, ctx)
    if "erro" in busca:
        return f"Não consegui consultar o catálogo: {busca['erro']}"
    produtos = busca["produtos"]

    quer_comprar = any(palavra in texto for palavra in PALAVRAS_COMPRA)
    achou_quantidade = re.search(r"\b(\d+)\b", texto)

    if quer_comprar and achou_quantidade:
        if not produtos:
            return "Não encontrei esse café no catálogo. Pode me dizer o nome?"
        produto = produtos[0]
        quantidade = int(achou_quantidade.group(1))
        pedido = ferramentas.executar(
            "criar_pedido",
            {"itens": [{"produto_id": produto["produto_id"], "quantidade": quantidade}]},
            ctx,
        )
        if "erro" in pedido:
            return f"Não consegui registrar o pedido: {pedido['erro']}"
        return (
            f"Pedido {pedido['pedido_id']} registrado: {quantidade}x {produto['nome']}. "
            f"Total {pedido['total_reais']} (desconto {pedido['desconto_reais']}). "
            "Ele fica pendente até a confirmação do estoque."
        )

    if not produtos:
        return "Não encontrei cafés com essa descrição. Quer tentar outras palavras?"
    linhas = ["Encontrei estes cafés:"]
    for p in produtos:
        notas = ", ".join(p["notas"])
        linhas.append(f"- {p['nome']} ({notas}): {p['preco_reais']}, {p['estoque']} em estoque")
    return "\n".join(linhas)
