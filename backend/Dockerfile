# ============================================================
# Stage 1 – builder
# Compiles/downloads everything heavy. This stage is DISCARDED
# from the final image; only the site-packages are copied out.
# ============================================================
FROM python:3.10-slim AS builder

# System build deps (only needed to compile wheels; not in final image)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /install

# Copy only the dependency manifest first so Docker can cache this layer.
# Re-running `pip install` only happens when requirements.txt changes.
COPY requirements.txt .

# 1. CPU-only PyTorch – install into a prefix dir so we can COPY it out.
#    --extra-index-url keeps the resolver from pulling CUDA variants.
RUN pip install --no-cache-dir --prefix=/install/deps \
        torch \
        --index-url https://download.pytorch.org/whl/cpu

# 2. Rest of the deps into the same prefix dir.
RUN pip install --no-cache-dir --prefix=/install/deps \
        -r requirements.txt

# 3. Pre-download the Legal-BERT model weights into the image so the
#    container starts instantly (no 400 MB download on every cold start).
#    The model is saved to /model_cache which we copy to the final image.
RUN pip install --no-cache-dir huggingface_hub && \
    python -c " \
from sentence_transformers import SentenceTransformer; \
m = SentenceTransformer('nlpaueb/legal-bert-base-uncased', cache_folder='/model_cache'); \
print('Model cached successfully') \
"

# ============================================================
# Stage 2 – final runtime image
# Starts from the same slim base; copies only what's needed.
# No build tools, no pip cache, no __pycache__ from the build.
# ============================================================
FROM python:3.10-slim AS runtime

# Minimal runtime system dep: libpq for asyncpg's C extension
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy compiled packages from builder (not pip, not build tools)
COPY --from=builder /install/deps /usr/local

# Copy pre-downloaded model weights
COPY --from=builder /model_cache /model_cache

# Tell sentence-transformers / HuggingFace to use our baked-in cache
ENV TRANSFORMERS_CACHE=/model_cache \
    HF_HOME=/model_cache \
    SENTENCE_TRANSFORMERS_HOME=/model_cache \
    # Keeps Python from writing .pyc files to the image layers
    PYTHONDONTWRITEBYTECODE=1 \
    # Prevents Python from buffering stdout/stderr (better for logs)
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy application source LAST (changes most often → cheapest cache miss)
COPY . .

# Drop all unnecessary files that leaked through
RUN find /app -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true && \
    find /app -name "*.pyc" -delete 2>/dev/null || true && \
    find /app -name "*.pyo" -delete 2>/dev/null || true && \
    # Remove alembic migrations and scripts from the runtime image;
    # migrations should be run as a separate init job, not inside the server.
    rm -rf /app/alembic /app/scripts /app/tests /app/venv /app/.venv

# Run as non-root for security hardening
RUN addgroup --system app && adduser --system --ingroup app app
USER app

EXPOSE 8000

# Use exec form (no shell wrapper) so signals reach uvicorn directly
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--no-access-log"]
