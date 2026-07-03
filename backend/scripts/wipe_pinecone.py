import os
from dotenv import load_dotenv
load_dotenv('../.env')
from pinecone import Pinecone

print("Connecting to Pinecone...")
pc = Pinecone(api_key=os.environ.get('PINECONE_API_KEY'))
index = pc.Index('writon-judgments')

print("Deleting all vectors in the index...")
index.delete(delete_all=True)
print("Successfully wiped all vectors from Pinecone!")
