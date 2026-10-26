FROM caddy:2.11.7-alpine AS caddy
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    RIVIAN_FINDER_CLOUD=1 \
    RIVIAN_FINDER_DATA_DIR=/data \
    TZ=America/Denver \
    PORT=8080

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=caddy /usr/bin/caddy /usr/local/bin/caddy
COPY requirements.txt ./
RUN python -m pip install -r requirements.txt
COPY app.py Caddyfile docker-entrypoint.sh ./
COPY rivian_finder/ ./rivian_finder/
COPY .streamlit/config.toml ./.streamlit/config.toml
RUN mkdir -p /data /app/static/photos

EXPOSE 8080
ENTRYPOINT ["/bin/bash", "/app/docker-entrypoint.sh"]
