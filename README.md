# Writon

AI-Powered Judiciary Drafting Platform.

## Project Structure

This is a Modular Monolith consisting of:
- **Frontend**: Next.js 14 App Router, Vanilla CSS
- **Backend**: Python FastAPI
- **Database**: Neon PostgreSQL with `pgvector`
- **Cache**: Redis
- **Storage**: Cloudflare R2
- **Auth**: Clerk
- **Payments**: Razorpay

## Quick Start (Local Development)

1. Copy `.env.example` to `.env` and fill in the required values.
2. Build and start the services using Docker Compose:

   ```bash
   docker-compose up --build
   ```

3. Access the frontend at `http://localhost:3000` and the backend API at `http://localhost:8000`.
