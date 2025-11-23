FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=1200 \
    PIP_RETRIES=20 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    U2NET_HOME=/app/artifacts/u2net \
    ECOGROW_MODEL_CACHE=/app/artifacts/pretrained

# librerie utili per build e Pillow (jpeg/zlib); poi le tieni perché leggere
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg62-turbo-dev \
    zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# copia i requirements e aggiorna pip prima di installare
COPY requirements.txt /app/requirements.txt

# usa anche il repo CPU di PyTorch (ruote precompilate)
# NB: se hai già messo torch/torchvision nel requirements, non toccarli: questo --extra-index-url basta
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt \
        --extra-index-url https://download.pytorch.org/whl/cpu

# copia il resto dell'app
COPY . /app
RUN chmod +x /app/infra/entrypoint_api.sh

EXPOSE 8000
ENTRYPOINT ["bash", "/app/infra/entrypoint_api.sh"]
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "app:create_app()"]
