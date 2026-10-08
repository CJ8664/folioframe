# SpectraFrame service image for Cloud Run.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ ./server/
WORKDIR /app/server

# Cloud Run injects $PORT; the server reads it. Local config.json is NOT
# baked in -- production config comes from mounted config or env.
EXPOSE 8080
CMD ["python3", "spectra_server.py"]
# Deploy verification trigger 3
# Deploy verification trigger 3
