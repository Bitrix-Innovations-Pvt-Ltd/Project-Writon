import os
from dotenv import load_dotenv
load_dotenv('.env')
from pinecone import Pinecone

pc = Pinecone(os.environ.get('PINECONE_API_KEY'))
index = pc.Index('writon-judgments')

from sentence_transformers import SentenceTransformer
model = SentenceTransformer('nlpaueb/legal-bert-base-uncased')
dense = model.encode('idbi').tolist()

res = index.query(vector=dense, top_k=5)
print("Query matches without sparse:", len(res.matches))
for m in res.matches:
    print(m.id, m.score)
