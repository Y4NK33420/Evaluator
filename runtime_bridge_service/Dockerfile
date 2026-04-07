FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY runtime_bridge_service/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY runtime_bridge_service/server.py /app/server.py

EXPOSE 8099

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8099"]
