FROM python:3.12-slim

ARG TARGETARCH=amd64

RUN apt-get update && apt-get install -y --no-install-recommends \
        iperf3 \
        curl \
    && case "${TARGETARCH}" in \
         amd64) LS_ARCH=linux_amd64 ;; \
         arm64) LS_ARCH=linux_arm64 ;; \
         *)     LS_ARCH=linux_amd64 ;; \
       esac \
    && curl -fsSL "https://github.com/librespeed/speedtest-cli/releases/download/v1.0.10/librespeed-cli_1.0.10_${LS_ARCH}.tar.gz" \
       | tar -xz -C /usr/local/bin librespeed-cli \
    && chmod +x /usr/local/bin/librespeed-cli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8766
CMD ["gunicorn", "--bind", "0.0.0.0:8766", "--timeout", "300", "--workers", "1", "app:app"]
