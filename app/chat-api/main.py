"""chat-api: rotas HTTP do vendedor de cafés (contrato em docs/contratos.md)."""

import logging
import socket
import uuid
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, StringConstraints

import pagina
from config import carregar_config
from repositorio import Repositorio
from vendedor import LLMIndisponivel, Vendedor

# Falha cedo: sem as variáveis obrigatórias o processo nem sobe.
config = carregar_config()

logging.basicConfig(
    level=config.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
# O httpx registra cada requisição em INFO; deixamos só avisos e erros.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("chat-api")

LIMITE_HISTORICO = 20
MENSAGEM_LLM_INDISPONIVEL = (
    "Nosso vendedor está indisponível no momento. "
    "Tente novamente em alguns instantes; nenhum pedido foi criado."
)

repo = Repositorio(config)
vendedor = Vendedor(config, repo)
log.info("chat-api iniciado llm_modo=%s regiao=%s", config.llm_modo, config.aws_region)

app = FastAPI(title="chat-api", description="Vendedor de cafés especiais da Grão")

# Em rede bridge o hostname é o ID curto do container: identifica a task que respondeu
# (útil para ver o ALB distribuindo as requisições).
TASK_ID = socket.gethostname()


@app.middleware("http")
async def identificar_task(request: Request, call_next):
    resposta = await call_next(request)
    resposta.headers["X-Task"] = TASK_ID
    return resposta


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def pagina_inicial():
    return pagina.HTML


class EntradaChat(BaseModel):
    conversa_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)] | None = None
    mensagem: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class SaidaChat(BaseModel):
    conversa_id: str
    resposta: str
    pedidos_criados: list[str]


# As rotas são "def" (e não "async def") porque boto3 e o cliente do LLM
# são bloqueantes; assim o FastAPI as executa em um pool de threads.

@app.get("/health")
def health():
    # Não toca em banco nem LLM: se eles caírem, as tasks não devem ser derrubadas.
    return {"status": "ok"}


@app.post("/chat", response_model=SaidaChat)
def chat(entrada: EntradaChat):
    conversa_id = entrada.conversa_id or str(uuid.uuid4())
    log.info("mensagem recebida conversa_id=%s", conversa_id)

    # O histórico é lido antes de gravar a mensagem nova, para não duplicá-la.
    historico = repo.carregar_historico(conversa_id, LIMITE_HISTORICO)
    repo.salvar_mensagem(conversa_id, "cliente", entrada.mensagem)

    try:
        resposta = vendedor.responder(conversa_id, entrada.mensagem, historico)
    except LLMIndisponivel:
        log.warning("LLM indisponivel, respondendo 503 conversa_id=%s", conversa_id)
        return JSONResponse(
            status_code=503,
            content={"detail": MENSAGEM_LLM_INDISPONIVEL, "conversa_id": conversa_id},
        )

    repo.salvar_mensagem(conversa_id, "vendedor", resposta.texto)
    log.info("resposta enviada conversa_id=%s pedidos_criados=%s",
             conversa_id, ",".join(resposta.pedidos_criados) or "-")
    return SaidaChat(
        conversa_id=conversa_id,
        resposta=resposta.texto,
        pedidos_criados=resposta.pedidos_criados,
    )


@app.get("/produtos")
def listar_produtos():
    return repo.listar_produtos()


@app.get("/pedidos/{pedido_id}")
def obter_pedido(pedido_id: str):
    pedido = repo.obter_pedido(pedido_id)
    if pedido is None:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    return pedido
