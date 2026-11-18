"""Leitura da configuração a partir de variáveis de ambiente.

Os nomes seguem docs/contratos.md. Se faltar alguma variável obrigatória,
o serviço nem sobe: é melhor falhar cedo do que no meio de uma conversa.
"""

import os
from dataclasses import dataclass, field

MODOS_LLM = ("real", "fake")


class ErroConfiguracao(Exception):
    pass


@dataclass(frozen=True)
class Config:
    aws_region: str
    tabela_produtos: str
    tabela_pedidos: str
    tabela_conversas: str
    fila_pedidos_url: str
    llm_modo: str
    dynamodb_endpoint_url: str | None = None
    sqs_endpoint_url: str | None = None
    llm_base_url: str | None = None
    model_id: str | None = None
    log_level: str = "INFO"
    # repr=False: a chave nunca aparece se alguém imprimir o objeto Config.
    llm_api_key: str | None = field(default=None, repr=False)


def _ler(nome: str) -> str | None:
    """Devolve o valor da variável ou None se estiver ausente ou vazia."""
    valor = os.environ.get(nome, "").strip()
    return valor or None


def carregar_config() -> Config:
    faltando = []

    def obrigatoria(nome: str) -> str:
        valor = _ler(nome)
        if valor is None:
            faltando.append(nome)
        return valor or ""

    aws_region = obrigatoria("AWS_REGION")
    tabela_produtos = obrigatoria("TABELA_PRODUTOS")
    tabela_pedidos = obrigatoria("TABELA_PEDIDOS")
    tabela_conversas = obrigatoria("TABELA_CONVERSAS")
    fila_pedidos_url = obrigatoria("FILA_PEDIDOS_URL")
    llm_modo = obrigatoria("LLM_MODO").lower()

    # Chave, URL e modelo do LLM só são necessários no modo real.
    if llm_modo == "real":
        llm_api_key = obrigatoria("LLM_API_KEY")
        llm_base_url = obrigatoria("LLM_BASE_URL")
        model_id = obrigatoria("MODEL_ID")
    else:
        llm_api_key = _ler("LLM_API_KEY")
        llm_base_url = _ler("LLM_BASE_URL")
        model_id = _ler("MODEL_ID")

    if faltando:
        raise ErroConfiguracao(
            "Variáveis de ambiente obrigatórias ausentes: " + ", ".join(faltando)
        )
    if llm_modo not in MODOS_LLM:
        raise ErroConfiguracao(
            f"LLM_MODO inválido: '{llm_modo}'. Use 'real' ou 'fake'."
        )

    return Config(
        aws_region=aws_region,
        tabela_produtos=tabela_produtos,
        tabela_pedidos=tabela_pedidos,
        tabela_conversas=tabela_conversas,
        fila_pedidos_url=fila_pedidos_url,
        llm_modo=llm_modo,
        dynamodb_endpoint_url=_ler("DYNAMODB_ENDPOINT_URL"),
        sqs_endpoint_url=_ler("SQS_ENDPOINT_URL"),
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        model_id=model_id,
        log_level=(_ler("LOG_LEVEL") or "INFO").upper(),
    )
