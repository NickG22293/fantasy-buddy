FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Generate a self-signed cert for localhost HTTPS (required by Yahoo OAuth redirect URI).
# The cert is baked into the image; rebuild to rotate it.
RUN openssl req -x509 -newkey rsa:2048 -nodes \
      -keyout auth/localhost.key \
      -out auth/localhost.crt \
      -days 3650 \
      -subj "/CN=localhost" \
      -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

# SQLite DB is written to /data so it can live on a named volume
ENV DB_PATH=/data/hockeybot.db

EXPOSE 8000

CMD ["python", "server.py"]
