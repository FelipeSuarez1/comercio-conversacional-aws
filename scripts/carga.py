"""Gerador de carga HTTP simples (só biblioteca padrão), para demonstrar a escala das tasks.

Por padrão bate em GET /produtos, que usa DynamoDB e CPU mas NÃO chama o LLM
(não gasta crédito da API). A cada 10 s imprime requisições/s, latência e erros.

Uso:
    python scripts/carga.py http://<dns-do-alb> --duracao 300 --concorrencia 40
    python scripts/carga.py http://localhost:8000 --caminho /health --duracao 30
"""

import argparse
import threading
import time
import urllib.error
import urllib.request


def percentil(valores, p):
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(len(ordenados) * p / 100))]


def main():
    parser = argparse.ArgumentParser(description="Gerador de carga HTTP")
    parser.add_argument("url_base", help="ex.: http://cafe-alb-123.us-east-2.elb.amazonaws.com")
    parser.add_argument("--caminho", default="/produtos")
    parser.add_argument("--duracao", type=int, default=300, help="segundos")
    parser.add_argument("--concorrencia", type=int, default=40, help="requisições simultâneas")
    args = parser.parse_args()

    url = args.url_base.rstrip("/") + args.caminho
    fim = time.time() + args.duracao
    trava = threading.Lock()
    janela = {"ok": 0, "erro": 0, "latencias": []}
    total = {"ok": 0, "erro": 0}

    def trabalhador():
        while time.time() < fim:
            inicio = time.time()
            try:
                with urllib.request.urlopen(url, timeout=30) as resposta:
                    resposta.read()
                    sucesso = resposta.status == 200
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                sucesso = False
            duracao_ms = (time.time() - inicio) * 1000
            with trava:
                janela["ok" if sucesso else "erro"] += 1
                total["ok" if sucesso else "erro"] += 1
                janela["latencias"].append(duracao_ms)

    threads = [threading.Thread(target=trabalhador, daemon=True) for _ in range(args.concorrencia)]
    for t in threads:
        t.start()

    print(f"Carga em {url}: {args.concorrencia} simultâneas por {args.duracao} s")
    print(f"{'tempo':>6} {'req/s':>7} {'p50 ms':>8} {'p95 ms':>8} {'erros':>6}")
    inicio_teste = time.time()
    while any(t.is_alive() for t in threads):
        time.sleep(10)
        with trava:
            ok, erro, lat = janela["ok"], janela["erro"], janela["latencias"]
            janela.update(ok=0, erro=0, latencias=[])
        decorrido = int(time.time() - inicio_teste)
        print(f"{decorrido:>5}s {(ok + erro) / 10:>7.1f} {percentil(lat, 50):>8.0f} "
              f"{percentil(lat, 95):>8.0f} {erro:>6}", flush=True)

    print(f"Total: {total['ok']} ok, {total['erro']} erros")


if __name__ == "__main__":
    main()
