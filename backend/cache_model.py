from sentence_transformers import SentenceTransformer, CrossEncoder
import torch

print("Pre-downloading Legal-BERT model weights...")
model = SentenceTransformer(
    "nlpaueb/legal-bert-base-uncased",
    cache_folder="/model_cache",
    device="cpu",
    model_kwargs={"dtype": torch.float32}
)
print("Legal-BERT cached successfully.")

print("Pre-downloading Cross-Encoder model weights...")
reranker = CrossEncoder(
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
    cache_dir="/model_cache",
    device="cpu",
    automodel_args={"dtype": torch.float32}
)
print("Cross-Encoder cached successfully.")
