"""Acesso ao DynamoDB (produtos, pedidos, conversas) e à fila SQS de pedidos."""

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config as BotoConfig

from config import Config

log = logging.getLogger(__name__)


def agora_iso() -> str:
    """Data e hora atual em ISO 8601 UTC com microssegundos (ex.: 2026-11-18T19:22:05.123456Z)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _sem_decimal(valor):
    """O boto3 devolve números do DynamoDB como Decimal; convertemos para int
    (todos os nossos números são inteiros: centavos, estoque, quantidade)."""
    if isinstance(valor, Decimal):
        return int(valor) if valor == valor.to_integral_value() else float(valor)
    if isinstance(valor, list):
        return [_sem_decimal(v) for v in valor]
    if isinstance(valor, dict):
        return {k: _sem_decimal(v) for k, v in valor.items()}
    return valor


class Repositorio:
    def __init__(self, config: Config):
        boto_config = BotoConfig(
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 3, "mode": "standard"},
        )
        # Os endpoints só são passados quando definidos (ambiente local).
        # Na AWS ficam None e o boto3 usa o endpoint padrão da região.
        dynamodb = boto3.resource(
            "dynamodb",
            region_name=config.aws_region,
            endpoint_url=config.dynamodb_endpoint_url,
            config=boto_config,
        )
        self.sqs = boto3.client(
            "sqs",
            region_name=config.aws_region,
            endpoint_url=config.sqs_endpoint_url,
            config=boto_config,
        )
        self.produtos = dynamodb.Table(config.tabela_produtos)
        self.pedidos = dynamodb.Table(config.tabela_pedidos)
        self.conversas = dynamodb.Table(config.tabela_conversas)
        self.fila_url = config.fila_pedidos_url

    # ---------- produtos ----------

    def listar_produtos(self) -> list[dict]:
        """Lê o catálogo inteiro (é pequeno). Ordena por nome para o resultado ser estável."""
        itens = []
        argumentos = {}
        while True:
            resposta = self.produtos.scan(**argumentos)
            itens.extend(resposta.get("Items", []))
            if "LastEvaluatedKey" not in resposta:
                break
            argumentos["ExclusiveStartKey"] = resposta["LastEvaluatedKey"]
        produtos = [_sem_decimal(item) for item in itens]
        return sorted(produtos, key=lambda p: p.get("nome", ""))

    def obter_produto(self, produto_id: str) -> dict | None:
        resposta = self.produtos.get_item(Key={"produto_id": produto_id})
        item = resposta.get("Item")
        return _sem_decimal(item) if item else None

    # ---------- pedidos ----------

    def salvar_pedido(self, pedido: dict) -> None:
        # A condição garante que nunca sobrescrevemos um pedido existente.
        self.pedidos.put_item(
            Item=pedido,
            ConditionExpression="attribute_not_exists(pedido_id)",
        )

    def obter_pedido(self, pedido_id: str) -> dict | None:
        resposta = self.pedidos.get_item(Key={"pedido_id": pedido_id})
        item = resposta.get("Item")
        return _sem_decimal(item) if item else None

    def enviar_para_fila(self, pedido_id: str) -> None:
        # A mensagem leva só o id; o worker relê o pedido no DynamoDB.
        self.sqs.send_message(
            QueueUrl=self.fila_url,
            MessageBody=json.dumps({"pedido_id": pedido_id}),
        )

    # ---------- conversas ----------

    def salvar_mensagem(self, conversa_id: str, papel: str, conteudo: str) -> None:
        self.conversas.put_item(
            Item={
                "conversa_id": conversa_id,
                "ts": agora_iso(),
                "papel": papel,
                "conteudo": conteudo,
            }
        )

    def carregar_historico(self, conversa_id: str, limite: int = 20) -> list[dict]:
        """Devolve as últimas `limite` mensagens da conversa, da mais antiga para a mais nova."""
        resposta = self.conversas.query(
            KeyConditionExpression=Key("conversa_id").eq(conversa_id),
            ScanIndexForward=False,  # mais novas primeiro, para o Limit pegar as últimas
            Limit=limite,
        )
        mensagens = [
            {"papel": item["papel"], "conteudo": item["conteudo"]}
            for item in resposta.get("Items", [])
            if item.get("papel") in ("cliente", "vendedor")
        ]
        mensagens.reverse()
        return mensagens
