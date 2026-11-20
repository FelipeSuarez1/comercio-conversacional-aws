"""Logs estruturados: um objeto JSON por linha no stdout (formato em docs/contratos.md).

Só biblioteca padrão. Os ids de correlação (request_id, conversa_id, pedido_id)
entram de dois jeitos:
- `extra={"pedido_id": ...}` na própria chamada de log;
- `contexto_log(conversa_id=...)`, que vale para todos os logs dentro do bloco
  (inclusive os de outros módulos chamados ali dentro).

O nível sai no campo "nivel" com o nome padrão (INFO, WARNING, ERROR...): o metric
filter "ERROR" do CloudWatch continua casando com as linhas de erro.

Este arquivo é igual em app/chat-api e app/order-worker (cada imagem copia o seu).
"""

import contextvars
import json
import logging
import sys
from contextlib import contextmanager
from datetime import datetime, timezone

_contexto = contextvars.ContextVar("contexto_log", default={})

# Atributos que todo LogRecord tem; o que sobrar veio de `extra=` e vai para o JSON.
_ATRIBUTOS_PADRAO = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message", "asctime", "taskName",
}


@contextmanager
def contexto_log(**campos):
    """Acrescenta campos (ex.: conversa_id) a todos os logs dentro do bloco. None é ignorado."""
    novos = {chave: valor for chave, valor in campos.items() if valor is not None}
    token = _contexto.set({**_contexto.get(), **novos})
    try:
        yield
    finally:
        _contexto.reset(token)


class FormatadorJSON(logging.Formatter):
    def __init__(self, servico):
        super().__init__()
        self.servico = servico

    def format(self, record):
        momento = datetime.fromtimestamp(record.created, timezone.utc)
        dados = {
            "timestamp": momento.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "nivel": record.levelname,
            "servico": self.servico,
            "logger": record.name,
            "mensagem": record.getMessage(),
        }
        dados.update(_contexto.get())
        for chave, valor in vars(record).items():
            if chave not in _ATRIBUTOS_PADRAO and not chave.startswith("_"):
                dados[chave] = valor
        if record.exc_info:
            # Traceback numa linha só (dentro do JSON): um erro = um evento no CloudWatch.
            dados["excecao"] = self.formatException(record.exc_info)
        return json.dumps(dados, ensure_ascii=False, default=str)


def configurar_logs(servico, nivel="INFO", loggers_externos=()):
    """Troca os handlers do logger raiz por um único handler JSON no stdout.

    `loggers_externos` (ex.: os do uvicorn) perdem os handlers próprios e passam a
    usar o da raiz, para tudo sair no mesmo formato.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(FormatadorJSON(servico))
    raiz = logging.getLogger()
    raiz.handlers[:] = [handler]
    raiz.setLevel(nivel)
    for nome in loggers_externos:
        externo = logging.getLogger(nome)
        externo.handlers[:] = []
        externo.propagate = True
    return handler
