# Stage 1 — récupère uniquement le binaire docker CLI (pas le daemon)
FROM docker:27-cli AS docker-bin

# Stage 2 — image finale
FROM python:3.12-slim

# Copie du CLI docker depuis l'image officielle (pas de daemon, pas de containerd, pas de runc)
COPY --from=docker-bin /usr/local/bin/docker /usr/local/bin/docker

# Installation du plugin docker compose (multi-arch : amd64 + arm64)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && ARCH=$(uname -m) \
    && case "$ARCH" in \
         x86_64)  COMPOSE_ARCH="x86_64"  ;; \
         aarch64) COMPOSE_ARCH="aarch64" ;; \
         *) echo "Unsupported arch: $ARCH" && exit 1 ;; \
       esac \
    && mkdir -p /usr/local/lib/docker/cli-plugins \
    && curl -fsSL "https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-${COMPOSE_ARCH}" \
         -o /usr/local/lib/docker/cli-plugins/docker-compose \
    && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME ["/data"]
EXPOSE 8765

CMD ["gunicorn", "--bind", "0.0.0.0:8765", "--workers", "1", "--threads", "4", "--timeout", "120", "run:app"]
