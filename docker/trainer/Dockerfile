# Vertex AI prebuilt PyTorch 2.4 GPU training image (Python 3.10, CUDA 12), the newest
# PyTorch GPU base Vertex publishes; pinned by digest so the base cannot move.
# Resolved from us-docker.pkg.dev/vertex-ai/training/pytorch-gpu.2-4.py310:latest on 2026-11-10.
FROM us-docker.pkg.dev/vertex-ai/training/pytorch-gpu.2-4.py310@sha256:db53e742b58d126fae7ca6fdb62997d71acdb1e0d13df5e267fa633f9c2fc40f
WORKDIR /app
ENV PYTHONUNBUFFERED=1 HF_HOME=/tmp/huggingface WANDB_DIR=/tmp
COPY docker/trainer/pyproject.toml docker/trainer/uv.lock /tmp/trainer/
# Install the locked set into the base interpreter, next to its torch.
RUN pip install --no-cache-dir uv==0.13.1 \
    && uv export --project /tmp/trainer --frozen --no-dev --no-emit-project \
       --format requirements-txt -o /tmp/trainer/requirements.txt \
    && python -m pip install --no-cache-dir --require-hashes -r /tmp/trainer/requirements.txt \
    && python -c "import torch, transformers, wandb; from transformers import ModernBertModel; print(torch.__version__, transformers.__version__, ModernBertModel.__name__)"
COPY cloud/__init__.py cloud/train.py cloud/train_pairs.py cloud/release.py ./cloud/
COPY services/rag_workflow/*.py ./services/rag_workflow/
COPY services/rag_workflow/examples/demo_manifest.json ./services/rag_workflow/examples/
ARG SOURCE_VERSION=unknown
ENV SOURCE_VERSION=$SOURCE_VERSION
# The base image's entrypoint wraps commands for the legacy prebuilt-training flow.
ENTRYPOINT []
CMD ["python", "-m", "cloud.train", "--help"]
