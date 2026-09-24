"""Fixed Cantonese photo-retrieval cases with recorded embeddinggemma vectors.

Tests replay the recorded vectors through the real ranking code, so tuning
thresholds or keyword boosts cannot silently regress. When the index or query
text format changes, re-record with `python manage.py record_retrieval_vectors`.
"""
import base64
import json
import struct
from datetime import date
from pathlib import Path

from .models import MemoryAsset
from .views import _memory_context_text, _memory_index_text, _memory_query_text

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
CASES_PATH = FIXTURE_DIR / "memory_retrieval_cases.json"
VECTORS_PATH = FIXTURE_DIR / "memory_retrieval_vectors.json"


def load_cases():
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def photo_asset(fields, **extra):
    captured_at = date.fromisoformat(fields["captured_at"]) if fields["captured_at"] else None
    return MemoryAsset(
        caption=fields["caption"], generated_caption=fields["generated_caption"],
        tags=fields["tags"], captured_at=captured_at, **extra,
    )


def query_texts(case):
    return _memory_query_text(case["text"]), _memory_context_text(case.get("previous"), case["text"])


def required_texts(cases):
    texts = [_memory_index_text(photo_asset(fields)) for fields in cases["photos"].values()]
    for case in cases["queries"]:
        texts.extend(text for text in query_texts(case) if text)
    return list(dict.fromkeys(texts))


def encode_vector(vector):
    return base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode("ascii")


def decode_vector(encoded):
    raw = base64.b64decode(encoded)
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))


def load_vectors():
    if not VECTORS_PATH.exists():
        return None, {}
    data = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    return data["model"], {text: decode_vector(vector) for text, vector in data["vectors"].items()}
