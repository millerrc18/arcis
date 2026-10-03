"""T7: version hashes, the per-symbol index, and rebuild."""
import json

import pytest

from arcis.recorder.errors import StorageLayoutError
from arcis.recorder.store import NewsStore, canonical_json
from arcis.recorder.versioning import EXCLUDED_FIELDS, VersionIndex, version_hash


def raw(article_id: int, headline: str = "h") -> dict:
    return {
        "id": article_id,
        "headline": headline,
        "summary": "s",
        "content": None,
        "author": "a",
        "created_at": "2026-10-02T10:00:00Z",
        "updated_at": "2026-10-02T10:00:00Z",
        "url": "https://example.com",
        "source": "TestWire",
        "symbols": ["AAPL"],
        "images": [],
    }


def test_excluded_fields_empty_and_documented():
    # T1 preflight found no volatile fields across identical responses.
    assert not EXCLUDED_FIELDS


def test_version_hash_is_stable_and_canonical():
    a = raw(1)
    b = dict(reversed(list(a.items())))  # key order must not matter
    assert version_hash(a) == version_hash(b)
    assert len(version_hash(a)) == 64


def test_version_hash_changes_with_content():
    assert version_hash(raw(1)) != version_hash(raw(1, headline="different"))


def test_version_hash_ignores_excluded_fields(monkeypatch):
    import arcis.recorder.versioning as v

    monkeypatch.setattr(v, "EXCLUDED_FIELDS", frozenset({"nonce"}))
    a = raw(1)
    b = dict(a, nonce="abc")
    assert v.version_hash(a) == v.version_hash(b)


def test_index_append_and_dedup(tmp_path):
    index = VersionIndex(tmp_path / "data")
    assert index.append("AAPL", 1, "hash1")
    assert not index.append("AAPL", 1, "hash1")
    assert index.lookup("AAPL", 1) == "hash1"
    assert index.lookup("AAPL", 999) is None
    path = tmp_path / "data" / "index" / "AAPL.jsonl"
    assert len(path.read_text().splitlines()) == 1


def test_index_rejects_bad_symbol(tmp_path):
    index = VersionIndex(tmp_path / "data")
    with pytest.raises(StorageLayoutError):
        index.append("../../etc", 1, "hash1")


def test_rebuild_rewrites_index_from_scratch(tmp_path):
    data = tmp_path / "data"
    store = NewsStore(data)
    index = VersionIndex(data)
    from arcis.recorder.client import Article, FetchedArticle

    for aid in (1, 2):
        r = raw(aid)
        store.append("AAPL", FetchedArticle(raw=r, article=Article(**r)))
    # Index only the first article, then rebuild.
    index.append("AAPL", 1, version_hash(raw(1)))
    assert index.lookup("AAPL", 2) is None
    assert index.rebuild() == []
    assert index.lookup("AAPL", 1) == version_hash(raw(1))
    assert index.lookup("AAPL", 2) == version_hash(raw(2))


def test_rebuild_detects_tampered_article(tmp_path):
    data = tmp_path / "data"
    store = NewsStore(data)
    index = VersionIndex(data)
    from arcis.recorder.client import Article, FetchedArticle

    r = raw(1)
    store.append("AAPL", FetchedArticle(raw=r, article=Article(**r)))
    index.append("AAPL", 1, version_hash(r))
    # Tamper with the stored article.
    path = data / "articles" / "AAPL" / "2026-10-02.jsonl"
    tampered = dict(r, headline="tampered")
    path.write_text(canonical_json(tampered) + "\n")
    errors = index.rebuild()
    assert any("version hash mismatch" in e for e in errors)


def test_rebuild_empty_store_ok(tmp_path):
    assert VersionIndex(tmp_path / "data").rebuild() == []


def test_index_entry_format(tmp_path):
    index = VersionIndex(tmp_path / "data")
    index.append("AAPL", 42, "deadbeef")
    entry = json.loads((tmp_path / "data" / "index" / "AAPL.jsonl").read_text().splitlines()[0])
    assert entry == {"id": 42, "version_hash": "deadbeef"}
