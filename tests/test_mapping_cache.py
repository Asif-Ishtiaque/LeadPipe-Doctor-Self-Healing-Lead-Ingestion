"""The mapping cache must remember a field it resolved to "no canonical
target", so repeat uploads of the same header don't re-invoke the (slow) LLM
for it -- the main repeat-upload latency win. But it must NOT cache an
"unknown" that came from Ollama being unreachable, or a transient outage would
poison a field as permanently unmapped. These pin both behaviours with the
network/LLM stubbed out."""

from app.mapping import mapper, rag_store
from app.mapping.llm_client import OllamaUnavailable


def _stub_store(monkeypatch) -> dict:
    store: dict[str, str] = {}
    monkeypatch.setattr(rag_store, "lookup_known_mapping", lambda s, f: store.get(f"{s}:{f}"))
    monkeypatch.setattr(rag_store, "remember_mapping", lambda s, f, c, v: store.__setitem__(f"{s}:{f}", c))
    monkeypatch.setattr(mapper, "_heuristic_match", lambda f: None)  # force "no match"
    return store


def test_unknown_mapping_is_cached_and_skips_llm_next_time(monkeypatch):
    store = _stub_store(monkeypatch)
    calls = {"n": 0}

    def fake_llm(field, samples):
        calls["n"] += 1
        return None  # model genuinely answered "unknown"

    monkeypatch.setattr(mapper, "_llm_match", fake_llm)
    records = [{"Company": "Acme"}]

    first = mapper.map_source_fields("csv_upload", records)
    assert first["Company"] is None
    assert calls["n"] == 1
    assert store["csv_upload:Company"] == rag_store.UNKNOWN_MAPPING  # cached as unknown

    second = mapper.map_source_fields("csv_upload", records)
    assert second["Company"] is None
    assert calls["n"] == 1  # LLM was NOT called again -- cache hit


def test_llm_outage_does_not_cache_unknown(monkeypatch):
    store = _stub_store(monkeypatch)

    def boom(field, samples):
        raise OllamaUnavailable("down")

    monkeypatch.setattr(mapper, "_llm_match", boom)
    records = [{"Weird Column": "y"}]

    result = mapper.map_source_fields("csv_upload", records)
    assert result["Weird Column"] is None
    # Nothing cached -- so once Ollama is back, this field is retried, not
    # stuck as permanently unmapped.
    assert "csv_upload:Weird Column" not in store
