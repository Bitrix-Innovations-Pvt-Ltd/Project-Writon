from sentence_transformers import SentenceTransformer, CrossEncoder

print("Pre-downloading Legal-BERT model weights...")
model = SentenceTransformer(
    "nlpaueb/legal-bert-base-uncased",
    cache_folder="/model_cache",
)
print("Legal-BERT cached successfully.")

print("Pre-downloading Cross-Encoder model weights...")
import torch
reranker = CrossEncoder(
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
    cache_dir="/model_cache",
    device="cpu",
    automodel_args={"torch_dtype": torch.float32}
)
print("Cross-Encoder cached successfully.")
