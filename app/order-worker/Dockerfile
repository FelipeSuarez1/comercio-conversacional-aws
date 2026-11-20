FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py log_json.py processador.py worker.py healthcheck.py ./

# Roda sem privilégios de root
RUN useradd --create-home --uid 10001 worker
USER worker

# Na AWS o ECS usa o healthCheck da task definition, que deve chamar o mesmo comando.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python healthcheck.py

CMD ["python", "worker.py"]
