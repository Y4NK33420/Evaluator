FROM vllm/vllm-openai@sha256:1272be9dbd3f94ceea27601747f10d4333e489115064978acfd616ad68d98359

ARG TRANSFORMERS_COMMIT=3a3b59cb1a7c0238c8d1072e35d3879c5faff48e

RUN apt-get update -qq \
    && apt-get install -y -q --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "git+https://github.com/huggingface/transformers.git@${TRANSFORMERS_COMMIT}"
