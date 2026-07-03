FROM python:3.10-slim

WORKDIR /app

# Install only runtime system deps (no build-essential in final image)
RUN apt-get update && apt-get install -y \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install CPU-only torch first to avoid pulling the huge CUDA version
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

# Download model at build time (stays cached in layer)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('nlpaueb/legal-bert-base-uncased')"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
