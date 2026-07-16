from sentence_transformers import SentenceTransformer, CrossEncoder

print("Pre-downloading Legal-BERT model weights...")
model = SentenceTransformer(
    "nlpaueb/legal-bert-base-uncased",
    cache_folder="/model_cache",
)
print("Legal-BERT cached successfully.")

print("Pre-downloading Cross-Encoder model weights...")
reranker = CrossEncoder(
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
    cache_dir="/model_cache",
)
print("Cross-Encoder cached successfully.")
