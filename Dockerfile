FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# SQLite DB is written to /data so it can live on a named volume
ENV DB_PATH=/data/hockeybot.db

EXPOSE 8000

CMD ["python", "server.py"]
