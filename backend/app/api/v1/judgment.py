import boto3
import os
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.judgment import Judgment

router = APIRouter(prefix="/judgment", tags=["judgment"])

@router.get("/{id}")
async def get_judgment(id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Judgment).where(Judgment.id == id))
    judgment = result.scalar_one_or_none()
    
    if not judgment:
        raise HTTPException(status_code=404, detail="Judgment not found")
        
    return {
        "id": judgment.id,
        "title": f"{judgment.petitioner or 'Unknown'} v. {judgment.respondent or 'Unknown'}",
        "year": judgment.year,
        "case_type": judgment.case_type,
        "summary": judgment.summary,
        "holding": judgment.holding,
        "full_text": judgment.full_text,
        "has_pdf": bool(judgment.pdf_s3_key)
    }

@router.get("/{id}/download")
async def download_judgment_pdf(id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Judgment.pdf_s3_key).where(Judgment.id == id))
    pdf_key = result.scalar_one_or_none()
    
    if not pdf_key:
        raise HTTPException(status_code=404, detail="PDF not available for this judgment")
        
    # Generate presigned URL from S3/R2 or return public URL
    try:
        aws_access_key = os.environ.get("CLOUDFLARE_R2_ACCESS_KEY_ID", os.environ.get("AWS_ACCESS_KEY_ID", ""))
        aws_secret_key = os.environ.get("CLOUDFLARE_R2_SECRET_ACCESS_KEY", os.environ.get("AWS_SECRET_ACCESS_KEY", ""))
        region = os.environ.get("AWS_REGION", "auto") # R2 uses 'auto'
        bucket_name = os.environ.get("CLOUDFLARE_R2_BUCKET_NAME", os.environ.get("AWS_S3_BUCKET", "writon-judgments"))
        endpoint_url = os.environ.get("CLOUDFLARE_R2_ENDPOINT_URL", os.environ.get("S3_ENDPOINT_URL")) # e.g. https://<account>.r2.cloudflarestorage.com
        public_domain = os.environ.get("S3_PUBLIC_DOMAIN") # e.g. https://pub-xxxx.r2.dev
        
        # If a public domain is provided (like Cloudflare R2 dev URL), use it directly
        if public_domain:
            return {"url": f"{public_domain.rstrip('/')}/{pdf_key}"}
            
        # If no valid AWS credentials are provided and no public domain, return default S3 format
        if not aws_access_key or not aws_secret_key:
            public_url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{pdf_key}"
            return {"url": public_url}

        s3_client = boto3.client(
            's3',
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=region,
            endpoint_url=endpoint_url
        )
        
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': pdf_key},
            ExpiresIn=3600 # 1 hour expiration
        )
        
        return {"url": presigned_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not generate download link: {str(e)}")
