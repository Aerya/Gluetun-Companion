FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        iperf3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8766
CMD ["gunicorn", "--bind", "0.0.0.0:8766", "--timeout", "300", "--workers", "1", "app:app"]
