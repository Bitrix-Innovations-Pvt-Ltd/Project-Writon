# Writon Architecture

## Core Features
- **Drafting (RAG)**: Hybrid retrieval using BM25 and pgvector to fetch relevant judgments and legal codes, followed by LLM generation streaming via SSE.
- **Precedent Search**: Full-text and semantic search over the corpus of judgments.
- **Document Verification**: OCR (AWS Textract / Tesseract) and LLM-based document classification to verify user uploads (vakalatnama, FIR, orders).

## Services
- **Auth Service**: Handles Clerk webhooks for user sync and subscription status.
- **Drafting Service**: Orchestrates the RAG pipeline. Generates context, reranks chunks via Cross-encoder, and streams output via SSE.
- **Search Service**: Handles precedent browsing with BM25 (P1) and semantic search (P2).
- **Doc Verify Service**: Secures R2 uploads, runs OCR, and validates document relevance.
- **Payment Service**: Integrates Razorpay for one-time credits and subscriptions.
- **Ingestion Worker**: Cron job scraping SCI/HC portals, chunking PDFs via legal-BERT, and upserting embeddings.

## Data Storage
- **PostgreSQL (Neon)**: Primary DB for users, drafts, payments, and vectorized judgment/code chunks.
- **Redis**: Session caching and rate limiting.
- **Cloudflare R2**: Secure object storage for uploaded user documents and raw judgment PDFs.
