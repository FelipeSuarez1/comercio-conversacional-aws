"""Popula o catálogo de cafés na tabela de produtos.

Uso:
    python scripts/seed.py                    # só grava os produtos (AWS ou local)
    python scripts/seed.py --criar-tabelas    # cria as 3 tabelas antes (uso local)

Na AWS as tabelas são criadas pela infraestrutura; por isso --criar-tabelas
existe só para o ambiente local (DynamoDB Local).

Variáveis de ambiente (docs/contratos.md): AWS_REGION, DYNAMODB_ENDPOINT_URL
(só local), TABELA_PRODUTOS, TABELA_PEDIDOS, TABELA_CONVERSAS.

É idempotente: rodar de novo não duplica nada. Cada produto é regravado
com os valores abaixo (inclusive o estoque, o que "reseta" o catálogo).
"""

import argparse
import os
import sys
import time

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

# Preço em centavos de um pacote de 250 g; estoque em pacotes.
PRODUTOS = [
    {
        "produto_id": "brasil-cerrado-mineiro",
        "nome": "Cerrado Mineiro",
        "descricao": "Café encorpado e doce, ótimo para o dia a dia e para espresso.",
        "origem": "Brasil - Cerrado Mineiro (MG)",
        "torra": "media",
        "notas": ["chocolate", "caramelo", "castanhas"],
        "preco_centavos": 3900,
        "estoque": 50,
    },
    {
        "produto_id": "brasil-mantiqueira-de-minas",
        "nome": "Mantiqueira de Minas",
        "descricao": "Cultivado em altitude, com acidez cítrica e final adocicado.",
        "origem": "Brasil - Serra da Mantiqueira (MG)",
        "torra": "clara",
        "notas": ["laranja", "mel", "floral"],
        "preco_centavos": 4800,
        "estoque": 30,
    },
    {
        "produto_id": "brasil-chapada-diamantina",
        "nome": "Chapada Diamantina",
        "descricao": "Microlote premiado da Bahia, frutado e com corpo sedoso.",
        "origem": "Brasil - Chapada Diamantina (BA)",
        "torra": "clara",
        "notas": ["frutas amarelas", "baunilha", "melaço"],
        "preco_centavos": 5900,
        "estoque": 15,
    },
    {
        "produto_id": "brasil-sul-de-minas",
        "nome": "Sul de Minas Torra Escura",
        "descricao": "Torra intensa e baixa acidez, para quem gosta de café forte.",
        "origem": "Brasil - Sul de Minas (MG)",
        "torra": "escura",
        "notas": ["cacau", "tostado", "especiarias"],
        "preco_centavos": 3500,
        "estoque": 80,
    },
    {
        "produto_id": "etiopia-yirgacheffe",
        "nome": "Etiópia Yirgacheffe",
        "descricao": "Clássico lavado etíope, leve e muito aromático.",
        "origem": "Etiópia - Yirgacheffe",
        "torra": "clara",
        "notas": ["frutado", "jasmim", "limão siciliano"],
        "preco_centavos": 6900,
        "estoque": 20,
    },
    {
        "produto_id": "colombia-huila",
        "nome": "Colômbia Huila",
        "descricao": "Equilibrado, com doçura marcante e acidez suave.",
        "origem": "Colômbia - Huila",
        "torra": "media",
        "notas": ["frutas vermelhas", "rapadura", "chocolate ao leite"],
        "preco_centavos": 5200,
        "estoque": 25,
    },
    {
        "produto_id": "quenia-nyeri",
        "nome": "Quênia Nyeri",
        "descricao": "Acidez vibrante e corpo suculento, típico dos cafés quenianos.",
        "origem": "Quênia - Nyeri",
        "torra": "clara",
        "notas": ["groselha", "tomate", "toranja"],
        "preco_centavos": 7400,
        "estoque": 10,
    },
    {
        "produto_id": "guatemala-antigua",
        "nome": "Guatemala Antigua",
        "descricao": "Cultivado em solo vulcânico, encorpado e levemente defumado.",
        "origem": "Guatemala - Antigua",
        "torra": "media",
        "notas": ["chocolate amargo", "especiarias", "defumado"],
        "preco_centavos": 5600,
        "estoque": 18,
    },
    {
        "produto_id": "indonesia-sumatra-mandheling",
        "nome": "Sumatra Mandheling",
        "descricao": "Corpo pesado e terroso, processado no método semi-lavado local.",
        "origem": "Indonésia - Sumatra",
        "torra": "escura",
        "notas": ["terroso", "cedro", "cacau"],
        "preco_centavos": 6200,
        "estoque": 12,
    },
    {
        # Estoque baixo de propósito: o smoke test tenta comprar 5 e espera REJEITADO.
        "produto_id": "panama-geisha",
        "nome": "Panamá Geisha",
        "descricao": "Variedade rara e muito floral; lote limitadíssimo.",
        "origem": "Panamá - Boquete",
        "torra": "clara",
        "notas": ["floral", "bergamota", "pêssego"],
        "preco_centavos": 9000,
        "estoque": 2,
    },
]


def variavel(nome):
    valor = os.environ.get(nome)
    if not valor:
        sys.exit(f"Erro: defina a variável de ambiente {nome}.")
    return valor


def esperar_dynamodb(cliente, tentativas=30):
    """O DynamoDB Local pode levar alguns segundos para aceitar conexões."""
    for _ in range(tentativas):
        try:
            cliente.list_tables()
            return
        except EndpointConnectionError:
            print("Aguardando o DynamoDB responder...")
            time.sleep(1)
    sys.exit("Erro: DynamoDB não respondeu a tempo.")


def criar_tabela(cliente, nome, chaves):
    """Cria a tabela se ainda não existir. `chaves`: [(atributo, "HASH"|"RANGE")]."""
    try:
        cliente.create_table(
            TableName=nome,
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": a, "KeyType": t} for a, t in chaves],
            AttributeDefinitions=[{"AttributeName": a, "AttributeType": "S"} for a, _ in chaves],
        )
        cliente.get_waiter("table_exists").wait(TableName=nome)
        print(f"Tabela {nome} criada.")
    except ClientError as erro:
        if erro.response["Error"]["Code"] != "ResourceInUseException":
            raise
        print(f"Tabela {nome} já existe.")


def main():
    parser = argparse.ArgumentParser(description="Popula o catálogo de cafés.")
    parser.add_argument(
        "--criar-tabelas",
        action="store_true",
        help="cria as tabelas antes de popular (só para o ambiente local)",
    )
    args = parser.parse_args()

    regiao = variavel("AWS_REGION")
    endpoint = os.environ.get("DYNAMODB_ENDPOINT_URL") or None  # ausente na AWS
    tabela_produtos = variavel("TABELA_PRODUTOS")

    cliente = boto3.client("dynamodb", region_name=regiao, endpoint_url=endpoint)
    esperar_dynamodb(cliente)

    if args.criar_tabelas:
        criar_tabela(cliente, tabela_produtos, [("produto_id", "HASH")])
        criar_tabela(cliente, variavel("TABELA_PEDIDOS"), [("pedido_id", "HASH")])
        criar_tabela(cliente, variavel("TABELA_CONVERSAS"), [("conversa_id", "HASH"), ("ts", "RANGE")])

    tabela = boto3.resource("dynamodb", region_name=regiao, endpoint_url=endpoint).Table(tabela_produtos)
    with tabela.batch_writer() as lote:
        for produto in PRODUTOS:
            lote.put_item(Item=produto)

    print(f"{len(PRODUTOS)} produtos gravados em {tabela_produtos}.")


if __name__ == "__main__":
    main()
