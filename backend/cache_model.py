"""
Pre-downloads and caches model weights into /model_cache at Docker build time.
This runs ONCE during `docker build` — not at runtime.
Using the modules approach avoids the meta-tensor .to(device) crash that affects
SentenceTransformer(..., device="cpu") with sentence-transformers 3.3.1 + torch 2.6.
"""
from sentence_transformers import SentenceTransformer, CrossEncoder
from sentence_transformers import models as st_models

print("Pre-downloading Legal-BERT model weights...")
# Build via modules API so no .to(device) is called on meta tensors
transformer = st_models.Transformer(
    "nlpaueb/legal-bert-base-uncased",
    cache_dir="/model_cache",
    model_args={"low_cpu_mem_usage": False},
)
pooling = st_models.Pooling(
    transformer.get_word_embedding_dimension(),
    pooling_mode_mean_tokens=True,
)
model = SentenceTransformer(modules=[transformer, pooling], cache_folder="/model_cache")
print("Legal-BERT cached successfully.")

print("Pre-downloading Cross-Encoder model weights...")
reranker = CrossEncoder(
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
    cache_dir="/model_cache",
    automodel_args={"low_cpu_mem_usage": False},
)
print("Cross-Encoder cached successfully.")
