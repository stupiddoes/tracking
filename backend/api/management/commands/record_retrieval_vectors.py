import json

from django.conf import settings
from django.core.management.base import BaseCommand

from api.retrieval_eval import VECTORS_PATH, encode_vector, load_cases, required_texts
from api.views import _embedding


class Command(BaseCommand):
    help = "Embed the photo-retrieval regression cases with the configured model and save the vectors."

    def handle(self, *args, **options):
        texts = required_texts(load_cases())
        vectors = {}
        for position, text in enumerate(texts, 1):
            vectors[text] = encode_vector(_embedding(text))
            self.stdout.write(f"[{position}/{len(texts)}] {text[:40]!r}")
        VECTORS_PATH.write_text(
            json.dumps({"model": settings.EMBEDDING_MODEL, "vectors": vectors}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        self.stdout.write(self.style.SUCCESS(f"Saved {len(vectors)} vectors to {VECTORS_PATH.name}."))
