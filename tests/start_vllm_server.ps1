# start_vllm_server.ps1
# Starts the GLM-OCR vLLM server in a Docker container.
# Mounts the local HuggingFace cache so the model is NOT re-downloaded.
# Exposes the server at http://localhost:8080
#
# Requirements:
#   - Docker Desktop running with NVIDIA GPU support enabled
#   - Model already cached at $env:USERPROFILE\.cache\huggingface (done after first ocr_test.py run)
#
# Usage:
#   .\tests\start_vllm_server.ps1
#   # Wait ~30s for "Application startup complete" in logs, then run ocr_sdk_test.py

$HF_CACHE = "$env:USERPROFILE\.cache\huggingface"
$CONTAINER_NAME = "glmocr-server"

# Stop any existing container
$existing = docker ps -q --filter "name=$CONTAINER_NAME" 2>$null
if ($existing) {
    Write-Host "Stopping existing $CONTAINER_NAME container..."
    docker stop $CONTAINER_NAME | Out-Null
}

Write-Host "Starting vLLM server for zai-org/GLM-OCR on port 8080..."
Write-Host "HF cache: $HF_CACHE -> /root/.cache/huggingface"
Write-Host ""

docker run --rm -d `
    --gpus all `
    --shm-size 2g `
    -p 8080:8080 `
    -v "${HF_CACHE}:/root/.cache/huggingface" `
    --name $CONTAINER_NAME `
    --entrypoint "/bin/bash" `
    vllm/vllm-openai:nightly `
    -c "apt-get update -qq && apt-get install -y -q git && pip install -q 'git+https://github.com/huggingface/transformers.git' && vllm serve zai-org/GLM-OCR --served-model-name glm-ocr --max-model-len 2048 --dtype float16 --enforce-eager --num-gpu-blocks-override 500 --no-enable-prefix-caching --port 8080 --allowed-local-media-path /"

Write-Host ""
Write-Host "Container started. Waiting for server to be ready..."
Write-Host "Streaming logs (Ctrl+C to stop watching, server keeps running):"
Write-Host ""

# Stream logs until we see startup complete
docker logs -f $CONTAINER_NAME 2>&1 | ForEach-Object {
    Write-Host $_
    if ($_ -match "Application startup complete" -or $_ -match "Uvicorn running") {
        Write-Host ""
        Write-Host "✅ vLLM server is ready at http://localhost:8080"
        Write-Host "   Run: .venv\Scripts\python.exe tests\ocr_sdk_test.py"
        # Can't easily break out of ForEach-Object, user can Ctrl+C
    }
}
