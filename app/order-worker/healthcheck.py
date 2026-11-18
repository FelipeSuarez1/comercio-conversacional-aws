"""Health check do container: sai com 0 se o loop gravou o heartbeat há menos de 60 s."""

import sys
import time

from config import ARQUIVO_HEARTBEAT, LIMITE_HEARTBEAT_SEGUNDOS


def main():
    try:
        with open(ARQUIVO_HEARTBEAT) as arquivo:
            ultimo = float(arquivo.read().strip())
    except (OSError, ValueError):
        return 1  # arquivo ausente ou ilegível: o loop não está rodando

    idade = time.time() - ultimo
    return 0 if idade < LIMITE_HEARTBEAT_SEGUNDOS else 1


if __name__ == "__main__":
    sys.exit(main())
