import boto3
import os
from botocore.client import Config
from dotenv import load_dotenv

# Try to load .env from root if backend doesn't have it
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), ".env"))

endpoint_url = os.getenv("CLOUDFLARE_R2_ENDPOINT_URL")
aws_access_key_id = os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID")
aws_secret_access_key = os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY")
bucket_name = os.getenv("CLOUDFLARE_R2_BUCKET_NAME")

s3_client = boto3.client(
    "s3",
    endpoint_url=endpoint_url,
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    config=Config(signature_version="s3v4"),
)

def upload_file_to_r2(file_obj, filename: str, content_type: str):
    """
    Uploads a file object to R2 and returns the key.
    The filename parameter should be the FULL path inside the bucket (e.g. drafting/Document/User/123/doc.pdf).
    """
    if not bucket_name:
        raise ValueError("R2 bucket name is not configured")
        
    s3_client.upload_fileobj(
        file_obj,
        bucket_name,
        filename,
        ExtraArgs={"ContentType": content_type}
    )
    
    return filename
