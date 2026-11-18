"""Processamento de um pedido, seguindo as 4 etapas de docs/contratos.md.

Este módulo não conhece a fila: recebe um cliente DynamoDB (boto3.client("dynamodb"))
e devolve o resultado. Quem decide apagar ou não a mensagem é o worker.py.
"""

import json
import logging
from datetime import datetime, timezone

from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError

log = logging.getLogger("order-worker.processador")

PENDENTE = "PENDENTE"
CONFIRMADO = "CONFIRMADO"
REJEITADO = "REJEITADO"
DUPLICADO = "DUPLICADO"  # não é um status do pedido, só um resultado do processamento

MOTIVO_SEM_ESTOQUE = "estoque insuficiente"

_desserializador = TypeDeserializer()


class MensagemInvalida(Exception):
    """O corpo da mensagem não é um JSON com pedido_id."""


class PedidoInexistente(Exception):
    """O pedido_id da mensagem não existe na tabela de pedidos."""


def extrair_pedido_id(corpo):
    """Lê o corpo {"pedido_id": "<uuid>"} e devolve o id."""
    try:
        dados = json.loads(corpo)
    except (TypeError, ValueError) as erro:
        raise MensagemInvalida(f"corpo não é JSON válido: {erro}") from erro

    if not isinstance(dados, dict):
        raise MensagemInvalida("corpo não é um objeto JSON")

    pedido_id = dados.get("pedido_id")
    if not isinstance(pedido_id, str) or not pedido_id.strip():
        raise MensagemInvalida("campo pedido_id ausente ou vazio")
    return pedido_id.strip()


def agora_iso():
    """Data e hora atuais em ISO 8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


def _codigo_do_erro(erro):
    return erro.response.get("Error", {}).get("Code")


class Processador:
    def __init__(self, dynamodb, tabela_pedidos, tabela_produtos, relogio=agora_iso):
        self.dynamodb = dynamodb
        self.tabela_pedidos = tabela_pedidos
        self.tabela_produtos = tabela_produtos
        self.relogio = relogio  # trocável nos testes

    def processar(self, pedido_id):
        """Processa o pedido e devolve CONFIRMADO, REJEITADO ou DUPLICADO.

        Levanta PedidoInexistente se o pedido não existir. Qualquer outra exceção
        significa "não deu para decidir": a mensagem deve voltar para a fila.
        """
        # Etapa 1: relê o pedido; se não estiver PENDENTE, a mensagem é duplicada.
        pedido = self._ler_pedido(pedido_id)
        status = pedido.get("status")
        if status != PENDENTE:
            log.info("pedido_id=%s já está %s; mensagem duplicada", pedido_id, status)
            return DUPLICADO

        quantidades = self._quantidades_por_produto(pedido_id, pedido.get("itens", []))
        agora = self.relogio()

        # Etapa 2: baixa de estoque + confirmação, tudo ou nada.
        try:
            self.dynamodb.transact_write_items(
                TransactItems=self._montar_transacao(pedido_id, quantidades, agora)
            )
        except ClientError as erro:
            if _codigo_do_erro(erro) != "TransactionCanceledException":
                raise
            return self._tratar_cancelamento(pedido_id, quantidades, erro, agora)

        log.info("pedido_id=%s confirmado; estoque baixado de %s", pedido_id, quantidades)
        return CONFIRMADO

    def _ler_pedido(self, pedido_id):
        resposta = self.dynamodb.get_item(
            TableName=self.tabela_pedidos,
            Key={"pedido_id": {"S": pedido_id}},
            ConsistentRead=True,  # o chat-api acabou de gravar o pedido
        )
        if "Item" not in resposta:
            raise PedidoInexistente(pedido_id)
        # Converte o formato do DynamoDB ({"S": "..."}, {"N": "..."}) em tipos Python.
        return {chave: _desserializador.deserialize(valor) for chave, valor in resposta["Item"].items()}

    def _quantidades_por_produto(self, pedido_id, itens):
        """Soma as quantidades por produto_id.

        Uma transação não aceita duas operações no mesmo item, então se o mesmo
        produto aparecer duas vezes no pedido as quantidades são somadas.
        """
        quantidades = {}
        for item in itens:
            produto_id = item.get("produto_id")
            quantidade = int(item.get("quantidade", 0))
            if not produto_id or quantidade <= 0:
                raise ValueError(f"pedido_id={pedido_id} tem item inválido: {item}")
            quantidades[produto_id] = quantidades.get(produto_id, 0) + quantidade
        return quantidades

    def _montar_transacao(self, pedido_id, quantidades, agora):
        operacoes = []

        # Um decremento condicional por produto: o estoque nunca fica negativo.
        # Se o produto não existir, "estoque" não existe e a condição também falha.
        for produto_id, quantidade in quantidades.items():
            operacoes.append({
                "Update": {
                    "TableName": self.tabela_produtos,
                    "Key": {"produto_id": {"S": produto_id}},
                    "UpdateExpression": "SET estoque = estoque - :qtd",
                    "ConditionExpression": "estoque >= :qtd",
                    "ExpressionAttributeValues": {":qtd": {"N": str(quantidade)}},
                }
            })

        # Por último o pedido; "status" é palavra reservada, por isso o #status.
        operacoes.append({
            "Update": {
                "TableName": self.tabela_pedidos,
                "Key": {"pedido_id": {"S": pedido_id}},
                "UpdateExpression": "SET #status = :confirmado, atualizado_em = :agora",
                "ConditionExpression": "#status = :pendente",
                "ExpressionAttributeNames": {"#status": "status"},
                "ExpressionAttributeValues": {
                    ":confirmado": {"S": CONFIRMADO},
                    ":pendente": {"S": PENDENTE},
                    ":agora": {"S": agora},
                },
            }
        })
        return operacoes

    def _tratar_cancelamento(self, pedido_id, quantidades, erro, agora):
        # CancellationReasons vem na mesma ordem de TransactItems:
        # primeiro um motivo por produto e, no fim, o motivo do pedido.
        motivos = [m.get("Code") for m in erro.response.get("CancellationReasons", [])]
        if len(motivos) != len(quantidades) + 1:
            raise erro  # resposta inesperada: melhor tentar de novo do que adivinhar

        *motivos_produtos, motivo_pedido = motivos

        # Outro worker já processou o pedido entre a leitura e a transação.
        if motivo_pedido == "ConditionalCheckFailed":
            log.info("pedido_id=%s deixou de estar PENDENTE; mensagem duplicada", pedido_id)
            return DUPLICADO

        sem_estoque = [
            produto_id
            for produto_id, motivo in zip(quantidades, motivos_produtos)
            if motivo == "ConditionalCheckFailed"
        ]
        if sem_estoque:
            # Etapa 3: falhou por estoque, o pedido é rejeitado.
            return self._rejeitar(pedido_id, sem_estoque, agora)

        # Ex.: TransactionConflict (outra transação no mesmo item). Tenta de novo depois.
        raise erro

    def _rejeitar(self, pedido_id, sem_estoque, agora):
        try:
            self.dynamodb.update_item(
                TableName=self.tabela_pedidos,
                Key={"pedido_id": {"S": pedido_id}},
                UpdateExpression="SET #status = :rejeitado, motivo = :motivo, atualizado_em = :agora",
                ConditionExpression="#status = :pendente",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":rejeitado": {"S": REJEITADO},
                    ":motivo": {"S": MOTIVO_SEM_ESTOQUE},
                    ":pendente": {"S": PENDENTE},
                    ":agora": {"S": agora},
                },
            )
        except ClientError as erro:
            if _codigo_do_erro(erro) == "ConditionalCheckFailedException":
                log.info("pedido_id=%s deixou de estar PENDENTE; mensagem duplicada", pedido_id)
                return DUPLICADO
            raise

        log.info("pedido_id=%s rejeitado: %s (sem estoque: %s)", pedido_id, MOTIVO_SEM_ESTOQUE, sem_estoque)
        return REJEITADO
