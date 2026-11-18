#!/usr/bin/env bash
# Smoke test de ponta a ponta (chat-api + fila + order-worker), em modo LLM fake.
#
# Uso:  bash scripts/smoke-test.sh
#       API_URL=http://meu-alb.exemplo bash scripts/smoke-test.sh
#
# Depende só de curl e python (sem jq). Sai com código 1 na primeira falha.

set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
PRODUTO_OK="brasil-cerrado-mineiro"   # estoque alto no seed
PRODUTO_ESCASSO="panama-geisha"       # estoque 2 no seed

# No Windows, "python3" pode ser só um atalho para a loja; testamos antes de usar.
if python3 -c "" >/dev/null 2>&1; then PYTHON=python3; else PYTHON=python; fi

falhar() { echo "FALHOU: $*" >&2; exit 1; }
ok()     { echo "OK: $*"; }

# Lê JSON da entrada padrão e imprime uma expressão sobre ele (d = JSON lido).
# Ex.: echo '{"a": 1}' | campo 'd["a"]'
campo() {
  "$PYTHON" -c 'import json, sys; d = json.loads(sys.stdin.buffer.read()); print(eval(sys.argv[1]))' "$1"
}

# Monta o corpo do POST /chat pedindo <quantidade> pacotes do produto <id>.
# O nome vem do próprio catálogo e o JSON sai com acentos escapados (á),
# o que evita problemas de codificação no Git Bash.
corpo_compra() {
  printf '%s' "$CATALOGO" | "$PYTHON" -c '
import json, sys
dados = json.loads(sys.stdin.buffer.read())
if isinstance(dados, dict):  # aceita lista pura ou {"produtos": [...]}
    dados = next(v for v in dados.values() if isinstance(v, list))
produto_id, quantidade = sys.argv[1], sys.argv[2]
nome = next(p["nome"] for p in dados if p["produto_id"] == produto_id)
print(json.dumps({"mensagem": f"quero {quantidade} pacotes de {nome}"}))
' "$1" "$2"
}

# Envia a mensagem de compra e imprime o id do primeiro pedido criado.
comprar() {
  local corpo resposta
  corpo=$(corpo_compra "$1" "$2") || falhar "produto $1 não encontrado em /produtos"
  resposta=$(curl -sS -f --max-time 60 -X POST "$API_URL/chat" \
    -H "Content-Type: application/json" --data-binary "$corpo") \
    || falhar "POST /chat retornou erro"
  printf '%s' "$resposta" | campo 'd["pedidos_criados"][0]' 2>/dev/null \
    || falhar "a conversa não criou pedido. Resposta: $resposta"
}

# Consulta o pedido até sair de PENDENTE (o worker usa long polling) e imprime o status.
esperar_status() {
  local status="PENDENTE"
  for _ in $(seq 1 30); do
    status=$(curl -sS -f --max-time 10 "$API_URL/pedidos/$1" | campo 'd["status"]') \
      || falhar "GET /pedidos/$1 retornou erro"
    [ "$status" != "PENDENTE" ] && break
    sleep 2
  done
  echo "$status"
}

echo "== Smoke test em $API_URL =="

# 1. /health (com algumas tentativas, a API pode estar subindo)
for i in $(seq 1 30); do
  if curl -sS -f --max-time 5 "$API_URL/health" >/dev/null 2>&1; then break; fi
  [ "$i" -eq 30 ] && falhar "/health não respondeu"
  sleep 2
done
status=$(curl -sS -f "$API_URL/health" | campo 'd["status"]')
[ "$status" = "ok" ] || falhar "/health retornou status '$status'"
ok "/health"

# 2. /produtos
CATALOGO=$(curl -sS -f --max-time 10 "$API_URL/produtos") || falhar "GET /produtos retornou erro"
ok "/produtos respondeu"

# 3. Compra com estoque suficiente -> CONFIRMADO
pedido=$(comprar "$PRODUTO_OK" 2)
echo "Pedido criado: $pedido (2 pacotes de $PRODUTO_OK)"
status=$(esperar_status "$pedido")
[ "$status" = "CONFIRMADO" ] || falhar "esperava CONFIRMADO, veio $status"
ok "pedido $pedido CONFIRMADO"

# 4. Compra acima do estoque -> REJEITADO
pedido=$(comprar "$PRODUTO_ESCASSO" 5)
echo "Pedido criado: $pedido (5 pacotes de $PRODUTO_ESCASSO, estoque 2)"
status=$(esperar_status "$pedido")
[ "$status" = "REJEITADO" ] || falhar "esperava REJEITADO, veio $status"
ok "pedido $pedido REJEITADO por estoque"

echo "== Smoke test passou =="
