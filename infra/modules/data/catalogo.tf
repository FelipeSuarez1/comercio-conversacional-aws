# Catálogo inicial (os mesmos 10 produtos de scripts/seed.py, que continua valendo
# para o ambiente local e para "resetar" o estoque).
# Preço em centavos de um pacote de 250 g; estoque em pacotes.

locals {
  produtos = [
    {
      produto_id     = "brasil-cerrado-mineiro"
      nome           = "Cerrado Mineiro"
      descricao      = "Café encorpado e doce, ótimo para o dia a dia e para espresso."
      origem         = "Brasil - Cerrado Mineiro (MG)"
      torra          = "media"
      notas          = ["chocolate", "caramelo", "castanhas"]
      preco_centavos = 3900
      estoque        = 50
    },
    {
      produto_id     = "brasil-mantiqueira-de-minas"
      nome           = "Mantiqueira de Minas"
      descricao      = "Cultivado em altitude, com acidez cítrica e final adocicado."
      origem         = "Brasil - Serra da Mantiqueira (MG)"
      torra          = "clara"
      notas          = ["laranja", "mel", "floral"]
      preco_centavos = 4800
      estoque        = 30
    },
    {
      produto_id     = "brasil-chapada-diamantina"
      nome           = "Chapada Diamantina"
      descricao      = "Microlote premiado da Bahia, frutado e com corpo sedoso."
      origem         = "Brasil - Chapada Diamantina (BA)"
      torra          = "clara"
      notas          = ["frutas amarelas", "baunilha", "melaço"]
      preco_centavos = 5900
      estoque        = 15
    },
    {
      produto_id     = "brasil-sul-de-minas"
      nome           = "Sul de Minas Torra Escura"
      descricao      = "Torra intensa e baixa acidez, para quem gosta de café forte."
      origem         = "Brasil - Sul de Minas (MG)"
      torra          = "escura"
      notas          = ["cacau", "tostado", "especiarias"]
      preco_centavos = 3500
      estoque        = 80
    },
    {
      produto_id     = "etiopia-yirgacheffe"
      nome           = "Etiópia Yirgacheffe"
      descricao      = "Clássico lavado etíope, leve e muito aromático."
      origem         = "Etiópia - Yirgacheffe"
      torra          = "clara"
      notas          = ["frutado", "jasmim", "limão siciliano"]
      preco_centavos = 6900
      estoque        = 20
    },
    {
      produto_id     = "colombia-huila"
      nome           = "Colômbia Huila"
      descricao      = "Equilibrado, com doçura marcante e acidez suave."
      origem         = "Colômbia - Huila"
      torra          = "media"
      notas          = ["frutas vermelhas", "rapadura", "chocolate ao leite"]
      preco_centavos = 5200
      estoque        = 25
    },
    {
      produto_id     = "quenia-nyeri"
      nome           = "Quênia Nyeri"
      descricao      = "Acidez vibrante e corpo suculento, típico dos cafés quenianos."
      origem         = "Quênia - Nyeri"
      torra          = "clara"
      notas          = ["groselha", "tomate", "toranja"]
      preco_centavos = 7400
      estoque        = 10
    },
    {
      produto_id     = "guatemala-antigua"
      nome           = "Guatemala Antigua"
      descricao      = "Cultivado em solo vulcânico, encorpado e levemente defumado."
      origem         = "Guatemala - Antigua"
      torra          = "media"
      notas          = ["chocolate amargo", "especiarias", "defumado"]
      preco_centavos = 5600
      estoque        = 18
    },
    {
      produto_id     = "indonesia-sumatra-mandheling"
      nome           = "Sumatra Mandheling"
      descricao      = "Corpo pesado e terroso, processado no método semi-lavado local."
      origem         = "Indonésia - Sumatra"
      torra          = "escura"
      notas          = ["terroso", "cedro", "cacau"]
      preco_centavos = 6200
      estoque        = 12
    },
    {
      # Estoque baixo de propósito: o smoke test tenta comprar 5 e espera REJEITADO.
      produto_id     = "panama-geisha"
      nome           = "Panamá Geisha"
      descricao      = "Variedade rara e muito floral; lote limitadíssimo."
      origem         = "Panamá - Boquete"
      torra          = "clara"
      notas          = ["floral", "bergamota", "pêssego"]
      preco_centavos = 9000
      estoque        = 2
    },
  ]
}

# Mesmos tipos que o boto3 grava no seed: texto = S, lista de textos = L de S, inteiro = N
resource "aws_dynamodb_table_item" "produto" {
  for_each = { for p in local.produtos : p.produto_id => p }

  table_name = aws_dynamodb_table.produtos.name
  hash_key   = aws_dynamodb_table.produtos.hash_key

  item = jsonencode({
    produto_id     = { S = each.value.produto_id }
    nome           = { S = each.value.nome }
    descricao      = { S = each.value.descricao }
    origem         = { S = each.value.origem }
    torra          = { S = each.value.torra }
    notas          = { L = [for n in each.value.notas : { S = n }] }
    preco_centavos = { N = tostring(each.value.preco_centavos) }
    estoque        = { N = tostring(each.value.estoque) }
  })

  lifecycle {
    # O worker baixa o estoque: um apply futuro não deve "corrigir" o item.
    # Para recarregar o catálogo, use scripts/seed.py.
    ignore_changes = [item]
  }
}
