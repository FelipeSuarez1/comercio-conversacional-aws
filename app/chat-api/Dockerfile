FROM python:3.12-slim

# Sem .pyc dentro da imagem e logs saindo na hora (sem buffer).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Usuário sem privilégios para rodar o serviço.
RUN useradd --create-home --uid 10001 app

# Dependências primeiro: a camada fica em cache enquanto o requirements não mudar.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

USER app

EXPOSE 8000

# Python puro (a imagem slim não tem curl). urlopen falha se a resposta não for 2xx.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
