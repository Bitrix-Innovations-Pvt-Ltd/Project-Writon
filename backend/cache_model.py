"""
Pre-downloads and caches model weights into /model_cache at Docker build time.
This runs ONCE during `docker build` — not at runtime.
Using the modules approach avoids the meta-tensor .to(device) crash that affects
SentenceTransformer(..., device="cpu") with sentence-transformers 3.3.1 + torch 2.6.
"""
from sentence_transformers import SentenceTransformer, CrossEncoder
from sentence_transformers import models as st_models

print("Pre-downloading Legal-BERT model weights...")
model = SentenceTransformer(
    "nlpaueb/legal-bert-base-uncased",
    cache_folder="/model_cache",
    device="cpu"
)
print("Legal-BERT cached successfully.")


print("Pre-downloading Cross-Encoder model weights...")
# sentence-transformers <4 uses cache_dir/automodel_args; >=4 renamed them to
# cache_folder/model_kwargs — select by signature so both pins work.
import inspect
_ce_params = inspect.signature(CrossEncoder.__init__).parameters
if "cache_folder" in _ce_params:
    _ce_kwargs = {"cache_folder": "/model_cache", "model_kwargs": {"low_cpu_mem_usage": False}}
else:
    _ce_kwargs = {"cache_dir": "/model_cache", "automodel_args": {"low_cpu_mem_usage": False}}
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", **_ce_kwargs)
print("Cross-Encoder cached successfully.")
