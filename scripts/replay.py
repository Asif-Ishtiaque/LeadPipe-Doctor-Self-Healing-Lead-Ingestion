"""Replays the committed sample data pack (data/sample_pack/) through a
running API -- this is the "replay" step in the fresh-clone acceptance
test: `docker compose up` -> `python -m scripts.replay` -> dashboard shows
leads. Also what the demo video's "leads flow live" scene runs against.

Run with: python -m scripts.replay
"""

import os
import sys
import time
from pathlib import Path

import requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
SAMPLE_PACK = Path(__file__).resolve().parents[1] / "data" / "sample_pack"


def wait_for_api(timeout: float = 180.0) -> None:
    print(f"Waiting for the API at {API_BASE_URL} ...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{API_BASE_URL}/health", timeout=5)
            if resp.ok:
                print("API is up.\n")
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise SystemExit(f"API never became healthy within {timeout}s -- is `docker compose up` running?")


def ingest_jsonl(endpoint: str, path: Path) -> None:
    print(f"Ingesting {path.name} -> POST {endpoint}")
    resp = requests.post(f"{API_BASE_URL}{endpoint}", data=path.read_bytes())
    resp.raise_for_status()
    print(" ", resp.json()["summary"])


def ingest_csv(endpoint: str, path: Path) -> None:
    print(f"Ingesting {path.name} -> POST {endpoint}")
    with path.open("rb") as f:
        resp = requests.post(f"{API_BASE_URL}{endpoint}", files={"file": (path.name, f, "text/csv")})
    resp.raise_for_status()
    print(" ", resp.json()["summary"])


def main():
    if not SAMPLE_PACK.exists():
        raise SystemExit(f"Sample pack not found at {SAMPLE_PACK} -- clone should include it, or run scripts.generate_data --out-dir data/sample_pack")

    wait_for_api()

    ingest_jsonl("/ingest/facebook", SAMPLE_PACK / "facebook_leads.jsonl")
    ingest_jsonl("/ingest/landing-page", SAMPLE_PACK / "landing_page.jsonl")
    ingest_csv("/ingest/instagram", SAMPLE_PACK / "instagram_export.csv")
    ingest_csv("/ingest/google-form", SAMPLE_PACK / "google_form.csv")

    stats = requests.get(f"{API_BASE_URL}/stats").json()
    print("\nDone. Final stats:")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
