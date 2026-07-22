"""Pre-warm the demo path so the on-stage CSV upload takes seconds, not
minutes.

The first upload of a never-seen column set is slow (measured live: ~80-210s)
because a cold qwen2.5:3b has to reload and the LLM resolves every unfamiliar
field. Both costs are one-time: the model stays resident afterwards, and each
(source, field-name) mapping is cached in ChromaDB, so a *repeat* upload of the
same headers hits the cache and returns in a couple of seconds.

This script pays that cost ahead of time, off-stage:
  1. Warms the local LLM (loads qwen2.5:3b into memory).
  2. Resolves + caches the mappings for the exact headers you'll demo, WITHOUT
     inserting any leads -- it calls the field mapper directly, so the database
     stays clean.
It then re-runs the mapping to prove the cache is warm and prints the speedup.

Run inside the API container (it has the app code + can reach ollama/chroma):
    docker compose exec api python -m scripts.prewarm_demo
    docker compose exec api python -m scripts.prewarm_demo /srv/data/my_demo.csv

Pass the CSV you plan to upload and it seeds that file's exact headers; with no
argument it seeds a representative "messy CRM export" header set.
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mapping import rag_store  # noqa: E402
from app.mapping.llm_client import OllamaUnavailable, generate  # noqa: E402
from app.mapping.mapper import map_source_fields  # noqa: E402
from app.schema.canonical import LeadSource  # noqa: E402

# A representative "messy export" header set, used when no CSV is given. These
# are deliberately not keyword-clean, so seeding them exercises the real LLM
# path (not just the synonym heuristic).
DEFAULT_HEADERS = [
    "Contact Person",
    "Work E-mail Address",
    "Best Phone",
    "Company",
    "Opted In For Marketing?",
    "Which Ad Brought You",
    "Signed Up On",
]


def _headers_from_csv(path: str) -> list[str]:
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        for row in csv.reader(fh):
            if row:
                return [h.strip() for h in row if h.strip()]
    return []


def _warm_llm() -> None:
    print("→ Warming the local LLM (loading qwen2.5:3b into memory)…", flush=True)
    t0 = time.perf_counter()
    try:
        generate('Reply with only the word: ready', timeout=180.0)
        print(f"  ✓ model warm in {time.perf_counter() - t0:.1f}s")
    except OllamaUnavailable:
        print("  ⚠ Ollama unreachable — mapping will fall back to the heuristic matcher.")


def _seed(headers: list[str]) -> None:
    # One sample record carrying the demo's headers. map_source_fields resolves
    # + caches every field; it never touches the leads table.
    record = [{h: "sample" for h in headers}]
    source = LeadSource.CSV_UPLOAD.value

    print(f"\n→ Seeding mappings for {len(headers)} columns: {', '.join(headers)}", flush=True)
    t0 = time.perf_counter()
    mapping = map_source_fields(source, record)
    cold = time.perf_counter() - t0

    # Second pass should hit the exact-match cache for every field.
    t1 = time.perf_counter()
    map_source_fields(source, record)
    warm = time.perf_counter() - t1

    print("\n  Column → canonical field")
    for col, canon in mapping.items():
        print(f"    {col:<28} → {canon or '(kept in raw_payload)'}")
    print(f"\n  Cold resolve: {cold:.1f}s   |   Cached re-resolve: {warm:.2f}s")


def main() -> None:
    if len(sys.argv) > 1:
        path = sys.argv[1]
        headers = _headers_from_csv(path)
        if not headers:
            print(f"No header row found in {path}", file=sys.stderr)
            sys.exit(1)
        print(f"Seeding from {path}")
    else:
        headers = DEFAULT_HEADERS
        print("No CSV given — seeding the default representative header set.")

    _warm_llm()
    _seed(headers)

    # Verify the RAG store is actually reachable/persisted, so a green result
    # here really means the demo upload will hit the cache.
    try:
        hit = rag_store.lookup_known_mapping(LeadSource.CSV_UPLOAD.value, headers[0])
        cached = hit is not None
    except Exception:
        cached = False

    print("\n" + ("=" * 60))
    if cached:
        print("✅ Warm and cached. Uploading a CSV with these exact headers on")
        print("   stage will now hit the cache and return in ~seconds.")
    else:
        print("⚠ Seeded the model, but the mapping cache couldn't be confirmed")
        print("  (Ollama/Chroma may be degraded). The upload will still work,")
        print("  just slower on the first cold run.")
    print("=" * 60)


if __name__ == "__main__":
    main()
