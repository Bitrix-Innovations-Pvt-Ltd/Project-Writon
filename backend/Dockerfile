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
# Re-running pip install only happens when requirements.txt changes.
COPY requirements.txt .

# Install all deps (including torch 2.6 CPU-only) in a single resolver pass.
# --extra-index-url makes the CPU wheel index available alongside PyPI so that
# torch==2.6.0 resolves to the ~1GB CPU build instead of the ~6GB CUDA build.
RUN pip install --no-cache-dir --prefix=/install/deps \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt

# 3. Pre-download the Legal-BERT model weights into the image so the
#    container starts instantly (no 400 MB download on every cold start).
#    We use a standalone Python script to avoid shell quoting / indentation
#    bugs that occur with multi-line python -c "..." in RUN commands.
COPY cache_model.py /tmp/cache_model.py
RUN PYTHONPATH=/install/deps/lib/python3.10/site-packages \
    python /tmp/cache_model.py

# ============================================================
# Stage 2 – final runtime image
# Starts from the same slim base; copies only what's needed.
# No build tools, no pip cache, no __pycache__ from the build.
# ============================================================
FROM python:3.10-slim AS runtime

# Minimal runtime system dep: libpq5 for asyncpg's C extension
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy compiled site-packages from builder (not pip, not build tools)
COPY --from=builder /install/deps /usr/local

# Copy pre-downloaded model weights
COPY --from=builder /model_cache /model_cache

# Tell HuggingFace / sentence-transformers to use our baked-in cache.
# ENV values must NOT have inline comments — that is invalid Dockerfile syntax.
ENV TRANSFORMERS_CACHE=/model_cache
ENV HF_HOME=/model_cache
ENV SENTENCE_TRANSFORMERS_HOME=/model_cache
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy application source LAST (changes most often = cheapest cache miss)
COPY . .

# Strip files that should not be in a running container
RUN find /app -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
    find /app -name "*.pyc" -o -name "*.pyo" | xargs rm -f 2>/dev/null; \
    rm -rf /app/alembic /app/scripts /app/tests /app/venv /app/.venv /app/cache_model.py

# Run as non-root for security hardening
RUN addgroup --system app && adduser --system --ingroup app app
USER app

EXPOSE 8000

# Exec form so signals (SIGTERM) reach uvicorn directly without a shell wrapper
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-access-log"]
