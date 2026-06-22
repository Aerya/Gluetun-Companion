# Stage 1 — récupère uniquement le binaire docker CLI (pas le daemon)
# docker:29.6.0-cli — tag précis pour récupérer les correctifs Go/containerd
#                    sans attendre que le tag flottant docker:29-cli soit rescanné.
FROM docker:29.6.0-cli AS docker-bin

# Stage 2 — compile docker compose avec les dépendances Go patchées.
# docker/compose v5.1.4 est la dernière release upstream disponible, mais son
# binaire précompilé embarque encore containerd v2.2.3 et Go 1.26.3. On garde
# donc la même version fonctionnelle de Compose, recompilée avec les versions
# corrigées signalées par Trivy.
FROM --platform=$BUILDPLATFORM golang:1.26.4-alpine AS compose-bin

ARG TARGETOS=linux
ARG TARGETARCH
ARG COMPOSE_VERSION=v5.1.4

RUN apk add --no-cache git \
    && git clone --depth 1 --branch "${COMPOSE_VERSION}" https://github.com/docker/compose.git /src

WORKDIR /src
RUN go mod edit -require=github.com/containerd/containerd/v2@v2.2.5 \
    && go mod tidy \
    && CGO_ENABLED=0 GOOS="${TARGETOS}" GOARCH="${TARGETARCH:-amd64}" \
       go build -trimpath -tags e2e \
         -ldflags "-w -X github.com/docker/compose/v5/internal.Version=${COMPOSE_VERSION}" \
         -o /out/docker-compose ./cmd

# Stage 3 — image finale
FROM python:3.12-slim

# Copie du CLI docker depuis l'image officielle (pas de daemon, pas de containerd, pas de runc)
COPY --from=docker-bin /usr/local/bin/docker /usr/local/bin/docker

# Plugin docker compose recompilé depuis la source avec les dépendances patchées.
COPY --from=compose-bin /out/docker-compose /usr/local/lib/docker/cli-plugins/docker-compose

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME ["/data"]
EXPOSE 8765

CMD ["gunicorn", "--bind", "0.0.0.0:8765", "--workers", "1", "--threads", "4", "--timeout", "120", "run:app"]
