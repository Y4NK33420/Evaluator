# ── OCR Service Docker Image ──────────────────────────────────────────────────
#
# Runs the FastAPI OCR service (CPU-only).
# PP-DocLayoutV3 weights are downloaded from HuggingFace on first start
# and cached in the /hf-cache volume (fast on subsequent starts).
#
# Build:  docker build -t ocr-service:latest ./ocr_service
# Run:    docker compose up  (preferred — see docker-compose.yml)

FROM python:3.11-slim

# System deps: git (for transformers install), libGL for cv2
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer-cached unless requirements change)
COPY ocr_service/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir \
        --index-url https://pypi.org/simple \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r /tmp/requirements.txt

# Copy the ocr module and the service entrypoint
COPY ocr/         /app/ocr/
COPY ocr_service/server.py /app/server.py

# HuggingFace model cache (mounted as volume in compose)
ENV HF_HOME=/hf-cache
ENV TRANSFORMERS_CACHE=/hf-cache

# Service config (overridden in docker-compose.yml)
ENV VLLM_URL=http://vllm-server:8080/v1
ENV VLLM_MODEL=glm-ocr
ENV LAYOUT_MODEL=PaddlePaddle/PP-DocLayoutV3_safetensors
ENV MAX_BATCH_SIZE=32

EXPOSE 8000

# Warm up: pre-download layout model at build time into the image layer
# (Comment this out if you prefer to download at runtime via a volume mount)
# RUN python -c "from ocr.layout import LayoutDetector; LayoutDetector.get()"

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-level", "info"]
