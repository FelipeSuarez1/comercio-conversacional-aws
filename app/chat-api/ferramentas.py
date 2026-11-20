"""Ferramentas (tools) que o vendedor pode chamar.

As mesmas funções são usadas pelo modo real (o LLM decide chamar) e pelo
modo fake (o vendedor determinístico chama direto). Erros viram um resultado
{"erro": "..."} devolvido ao modelo, sem derrubar a requisição.
"""

import inspect
import json
import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass, field

from repositorio import Repositorio, agora_iso

log = logging.getLogger(__name__)

PERCENTUAL_DESCONTO = 10
QUANTIDADE_PARA_DESCONTO = 3
MAXIMO_RESULTADOS_BUSCA = 10

# Palavras comuns que não ajudam a achar um produto.
PALAVRAS_IGNORADAS = {
    "cafe", "cafes", "com", "para", "por", "uma", "umas", "uns", "dos", "das",
    "nos", "nas", "que", "tem", "ate", "mais", "menos", "algum", "alguma",
    "pacote", "pacotes", "reais", "sabor", "voce", "voces", "gostaria", "queria",
}


class ErroFerramenta(Exception):
    """Erro de validação que deve ser explicado ao modelo (e ao cliente)."""


@dataclass
class Contexto:
    """O que as ferramentas precisam saber além dos argumentos do modelo."""
    repo: Repositorio
    conversa_id: str
    pedidos_criados: list[str] = field(default_factory=list)


# ---------- utilitários ----------

def formatar_reais(centavos: int) -> str:
    """5990 -> 'R$ 59,90'; 123456 -> 'R$ 1.234,56'."""
    reais, resto = divmod(int(centavos), 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{resto:02d}"


def normalizar(texto: str) -> str:
    """Minúsculas e sem acentos, para comparar 'Etiópia' com 'etiopia'."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sem_acento.lower()


def palavras_busca(texto: str) -> list[str]:
    palavras = re.findall(r"[a-z0-9]+", normalizar(texto))
    return [
        p for p in palavras
        if len(p) >= 3 and not p.isdigit() and p not in PALAVRAS_IGNORADAS
    ]


def _texto_do_produto(produto: dict) -> str:
    partes = [
        produto.get("nome", ""),
        produto.get("descricao", ""),
        produto.get("origem", ""),
        produto.get("torra", ""),
        " ".join(produto.get("notas", [])),
    ]
    return normalizar(" ".join(partes))


def _inteiro_positivo(valor, nome: str) -> int:
    # bool é subclasse de int em Python; não queremos aceitar true/false.
    if isinstance(valor, bool):
        raise ErroFerramenta(f"{nome} deve ser um número inteiro.")
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ErroFerramenta(f"{nome} deve ser um número inteiro.")
    if not numero.is_integer():
        raise ErroFerramenta(f"{nome} deve ser um número inteiro.")
    if numero <= 0:
        raise ErroFerramenta(f"{nome} deve ser maior que zero.")
    return int(numero)


# ---------- ferramentas ----------

def buscar_produtos(ctx: Contexto, texto: str | None = None,
                    preco_maximo_reais: float | None = None) -> dict:
    preco_maximo_centavos = None
    if preco_maximo_reais is not None:
        if isinstance(preco_maximo_reais, bool):
            raise ErroFerramenta("preco_maximo_reais deve ser um número.")
        try:
            preco_maximo_centavos = round(float(preco_maximo_reais) * 100)
        except (TypeError, ValueError):
            raise ErroFerramenta("preco_maximo_reais deve ser um número.")
        if preco_maximo_centavos < 0:
            raise ErroFerramenta("preco_maximo_reais não pode ser negativo.")

    palavras = palavras_busca(texto or "")
    encontrados = []
    for produto in ctx.repo.listar_produtos():
        if preco_maximo_centavos is not None and produto["preco_centavos"] > preco_maximo_centavos:
            continue
        if palavras:
            texto_produto = _texto_do_produto(produto)
            acertos = sum(1 for p in palavras if p in texto_produto)
            if acertos == 0:
                continue
        else:
            acertos = 0  # sem texto: todos os produtos (dentro do preço) servem
        encontrados.append((acertos, produto))

    # Mais palavras casadas primeiro; em empate vale a ordem por nome do catálogo.
    encontrados.sort(key=lambda par: par[0], reverse=True)
    produtos = [
        {
            "produto_id": p["produto_id"],
            "nome": p["nome"],
            "notas": p.get("notas", []),
            "preco_reais": formatar_reais(p["preco_centavos"]),
            "estoque": p.get("estoque", 0),
        }
        for _, p in encontrados[:MAXIMO_RESULTADOS_BUSCA]
    ]
    return {"produtos": produtos, "total_encontrado": len(encontrados)}


def calcular_itens(ctx: Contexto, itens) -> tuple[list[dict], int, int]:
    """Valida os itens e calcula preços a partir do banco.

    Devolve (itens do pedido, desconto em centavos, total em centavos).
    """
    if not isinstance(itens, list) or not itens:
        raise ErroFerramenta("Informe ao menos um item com produto_id e quantidade.")

    # Soma quantidades repetidas do mesmo produto, para o desconto valer
    # sobre a quantidade total daquele produto.
    quantidades: dict[str, int] = {}
    for item in itens:
        if not isinstance(item, dict) or not item.get("produto_id"):
            raise ErroFerramenta("Cada item precisa de produto_id e quantidade.")
        produto_id = str(item["produto_id"]).strip()
        quantidade = _inteiro_positivo(item.get("quantidade"), "quantidade")
        quantidades[produto_id] = quantidades.get(produto_id, 0) + quantidade

    itens_pedido = []
    subtotal = 0
    desconto = 0
    for produto_id, quantidade in quantidades.items():
        produto = ctx.repo.obter_produto(produto_id)
        if produto is None:
            raise ErroFerramenta(
                f"Produto '{produto_id}' não existe no catálogo. Use buscar_produtos para ver os ids."
            )
        preco = produto["preco_centavos"]  # preço sempre do banco
        valor_item = preco * quantidade
        subtotal += valor_item
        if quantidade >= QUANTIDADE_PARA_DESCONTO:
            # 10% com arredondamento para o centavo mais próximo (meio centavo sobe).
            desconto += (valor_item * PERCENTUAL_DESCONTO + 50) // 100
        itens_pedido.append({
            "produto_id": produto_id,
            "nome": produto["nome"],
            "quantidade": quantidade,
            "preco_unitario_centavos": preco,
        })

    return itens_pedido, desconto, subtotal - desconto


def criar_pedido(ctx: Contexto, itens=None) -> dict:
    itens_pedido, desconto, total = calcular_itens(ctx, itens)

    pedido_id = str(uuid.uuid4())
    agora = agora_iso()
    pedido = {
        "pedido_id": pedido_id,
        "conversa_id": ctx.conversa_id,
        "itens": itens_pedido,
        "desconto_centavos": desconto,
        "total_centavos": total,
        "status": "PENDENTE",
        "criado_em": agora,
        "atualizado_em": agora,
    }
    ids = {"conversa_id": ctx.conversa_id, "pedido_id": pedido_id}
    ctx.repo.salvar_pedido(pedido)
    log.info("pedido gravado", extra={**ids, "total_centavos": total})

    try:
        ctx.repo.enviar_para_fila(pedido_id, ctx.conversa_id)
    except Exception:
        # O pedido ficou gravado como PENDENTE, mas o worker não vai recebê-lo.
        log.error("pedido gravado mas não enviado para a fila", extra=ids)
        raise
    ctx.pedidos_criados.append(pedido_id)
    log.info("pedido enviado para a fila", extra=ids)

    return {
        "pedido_id": pedido_id,
        "total_reais": formatar_reais(total),
        "desconto_reais": formatar_reais(desconto),
        "status": "PENDENTE",
    }


def consultar_estoque(ctx: Contexto, produto_id: str | None = None,
                      nome: str | None = None) -> dict:
    """Estoque de um café, pelo produto_id exato ou pelo nome (busca aproximada)."""
    if not produto_id and not nome:
        raise ErroFerramenta("Informe o produto_id ou o nome do café.")

    produto = None
    if produto_id:
        produto = ctx.repo.obter_produto(str(produto_id).strip())

    parecidos = []
    if produto is None:
        # Sem id exato: procura pelo nome (o id errado também serve como texto).
        termo = str(nome or produto_id)
        palavras = palavras_busca(termo.replace("-", " "))
        candidatos = []
        for p in ctx.repo.listar_produtos():
            alvo = normalizar(f"{p.get('nome', '')} {p['produto_id']}")
            acertos = sum(1 for w in palavras if w in alvo)
            if acertos:
                candidatos.append((acertos, p))
        if not candidatos:
            raise ErroFerramenta(
                f"Não encontrei o café '{termo}' no catálogo. Use buscar_produtos para ver os ids."
            )
        candidatos.sort(key=lambda par: par[0], reverse=True)
        produto = candidatos[0][1]
        parecidos = [p["nome"] for _, p in candidatos[1:MAXIMO_RESULTADOS_BUSCA]]

    estoque = int(produto.get("estoque", 0))
    resultado = {
        "produto_id": produto["produto_id"],
        "nome": produto["nome"],
        "estoque": estoque,
        "disponivel": estoque > 0,
        "preco_reais": formatar_reais(produto["preco_centavos"]),
    }
    if parecidos:
        resultado["outros_parecidos"] = parecidos
    return resultado


def consultar_pedido(ctx: Contexto, pedido_id: str | None = None) -> dict:
    """Status, itens e total de um pedido (os mesmos dados de GET /pedidos/{id})."""
    if not isinstance(pedido_id, str) or not pedido_id.strip():
        raise ErroFerramenta("Informe o número do pedido (pedido_id).")
    pedido_id = pedido_id.strip()

    pedido = ctx.repo.obter_pedido(pedido_id)
    if pedido is None:
        raise ErroFerramenta(f"Pedido '{pedido_id}' não encontrado.")
    log.info("pedido consultado",
             extra={"conversa_id": ctx.conversa_id, "pedido_id": pedido_id,
                    "status": pedido.get("status")})

    resultado = {
        "pedido_id": pedido["pedido_id"],
        "status": pedido.get("status"),
        "itens": [
            {
                "produto_id": item.get("produto_id"),
                "nome": item.get("nome"),
                "quantidade": item.get("quantidade"),
                "preco_unitario_reais": formatar_reais(item.get("preco_unitario_centavos", 0)),
            }
            for item in pedido.get("itens", [])
        ],
        "desconto_reais": formatar_reais(pedido.get("desconto_centavos", 0)),
        "total_reais": formatar_reais(pedido.get("total_centavos", 0)),
        "criado_em": pedido.get("criado_em"),
        "atualizado_em": pedido.get("atualizado_em"),
    }
    if pedido.get("motivo"):
        resultado["motivo"] = pedido["motivo"]
    return resultado


# ---------- definição para o modelo e despacho ----------

FERRAMENTAS = {
    "buscar_produtos": buscar_produtos,
    "criar_pedido": criar_pedido,
    "consultar_estoque": consultar_estoque,
    "consultar_pedido": consultar_pedido,
}

# Formato "tools" da API de chat completions (compatível com OpenAI).
DEFINICOES = [
    {
        "type": "function",
        "function": {
            "name": "buscar_produtos",
            "description": (
                "Busca cafés no catálogo da loja. Use sempre antes de recomendar ou "
                "citar preço. Sem filtros, devolve o catálogo todo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "texto": {
                        "type": "string",
                        "description": (
                            "Palavras para procurar no nome, descrição, notas sensoriais, "
                            "origem ou torra. Ex.: 'frutado', 'etiopia', 'escura'."
                        ),
                    },
                    "preco_maximo_reais": {
                        "type": "number",
                        "description": "Preço máximo por pacote de 250 g, em reais. Ex.: 60.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "criar_pedido",
            "description": (
                "Registra o pedido do cliente. Só chame depois que o cliente confirmar "
                "os itens e as quantidades. Preço e desconto são calculados pela loja."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "itens": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "produto_id": {
                                    "type": "string",
                                    "description": "Id do produto, como veio de buscar_produtos.",
                                },
                                "quantidade": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "description": "Número de pacotes de 250 g.",
                                },
                            },
                            "required": ["produto_id", "quantidade"],
                        },
                    },
                },
                "required": ["itens"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_estoque",
            "description": (
                "Consulta o estoque atual de um café específico. Use quando o cliente "
                "perguntar se um café tem estoque ou quantos pacotes há. Informe o "
                "produto_id (de buscar_produtos) ou, se não souber, o nome."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "produto_id": {
                        "type": "string",
                        "description": "Id do produto, como veio de buscar_produtos.",
                    },
                    "nome": {
                        "type": "string",
                        "description": "Nome ou parte do nome do café. Ex.: 'geisha'.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_pedido",
            "description": (
                "Consulta um pedido já feito: status (PENDENTE, CONFIRMADO ou REJEITADO), "
                "motivo da rejeição, itens e total. Use quando o cliente perguntar pelo "
                "pedido dele; o número do pedido aparece na conversa depois de criar_pedido."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pedido_id": {
                        "type": "string",
                        "description": "Número (id) do pedido, como veio de criar_pedido.",
                    },
                },
                "required": ["pedido_id"],
            },
        },
    },
]


def executar(nome: str, argumentos, ctx: Contexto) -> dict:
    """Executa uma ferramenta e sempre devolve um dicionário (resultado ou erro).

    `argumentos` pode ser um dict ou o texto JSON que o modelo mandou.
    """
    funcao = FERRAMENTAS.get(nome)
    if funcao is None:
        return {"erro": f"Ferramenta desconhecida: {nome}"}

    if isinstance(argumentos, str):
        try:
            argumentos = json.loads(argumentos) if argumentos.strip() else {}
        except json.JSONDecodeError:
            return {"erro": "Argumentos inválidos: não é um JSON válido."}
    if not isinstance(argumentos, dict):
        return {"erro": "Argumentos inválidos: esperava um objeto JSON."}

    # Confere se os nomes dos argumentos batem com a função antes de chamá-la.
    try:
        inspect.signature(funcao).bind(ctx, **argumentos)
    except TypeError:
        return {"erro": f"Argumentos inválidos para {nome}."}

    try:
        return funcao(ctx, **argumentos)
    except ErroFerramenta as erro:
        log.info("ferramenta recusou", extra={"ferramenta": nome, "conversa_id": ctx.conversa_id,
                                              "motivo": str(erro)})
        return {"erro": str(erro)}
    except Exception:
        # Falha inesperada (ex.: DynamoDB ou SQS fora do ar): registra e avisa o modelo.
        log.exception("erro ao executar ferramenta",
                      extra={"ferramenta": nome, "conversa_id": ctx.conversa_id})
        return {"erro": "Falha interna ao executar a ferramenta. Tente novamente mais tarde."}
