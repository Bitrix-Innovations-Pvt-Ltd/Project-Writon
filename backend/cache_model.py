from sentence_transformers import SentenceTransformer

print("Pre-downloading Legal-BERT model weights...")
model = SentenceTransformer(
    "nlpaueb/legal-bert-base-uncased",
    cache_folder="/model_cache",
)
print("Model cached successfully.")
