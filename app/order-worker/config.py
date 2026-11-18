"""Configuração do order-worker, lida das variáveis de ambiente (docs/contratos.md)."""

import os
from dataclasses import dataclass

# Arquivo que o loop atualiza a cada volta; o healthcheck.py confere a idade dele.
ARQUIVO_HEARTBEAT = "/tmp/heartbeat"
LIMITE_HEARTBEAT_SEGUNDOS = 60

NIVEIS_DE_LOG = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ErroDeConfiguracao(Exception):
    """Variável obrigatória ausente ou com valor inválido."""


@dataclass(frozen=True)
class Config:
    regiao: str
    fila_pedidos_url: str
    tabela_pedidos: str
    tabela_produtos: str
    dynamodb_endpoint_url: str | None
    sqs_endpoint_url: str | None
    log_level: str


def _obrigatoria(nome):
    valor = os.environ.get(nome, "").strip()
    if not valor:
        raise ErroDeConfiguracao(f"variável de ambiente {nome} não definida")
    return valor


def _opcional(nome):
    # Endpoints locais (DynamoDB Local, ElasticMQ). Na AWS ficam ausentes.
    valor = os.environ.get(nome, "").strip()
    return valor or None


def carregar_config():
    log_level = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    if log_level not in NIVEIS_DE_LOG:
        raise ErroDeConfiguracao(f"LOG_LEVEL inválido: {log_level}")

    return Config(
        regiao=_obrigatoria("AWS_REGION"),
        fila_pedidos_url=_obrigatoria("FILA_PEDIDOS_URL"),
        tabela_pedidos=_obrigatoria("TABELA_PEDIDOS"),
        tabela_produtos=_obrigatoria("TABELA_PRODUTOS"),
        dynamodb_endpoint_url=_opcional("DYNAMODB_ENDPOINT_URL"),
        sqs_endpoint_url=_opcional("SQS_ENDPOINT_URL"),
        log_level=log_level,
    )
