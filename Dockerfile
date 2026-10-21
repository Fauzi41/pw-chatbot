FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Bake the knowledge base at build time (scrapes the 7 source URLs, ~1 req/10s)
RUN python ingest.py

ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "gunicorn -w 1 --threads 4 -b 0.0.0.0:${PORT} app:app"]
