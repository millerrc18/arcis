"""T6: the append-only store — layout, dedup, manifests, verify."""
import json

import pytest

from arcis.recorder.client import Article, FetchedArticle
from arcis.recorder.errors import StorageLayoutError, StoreError
from arcis.recorder.store import NewsStore, parse_day


def fetched(article_id: int, created_at: str, symbol: str = "AAPL") -> FetchedArticle:
    raw = {
        "id": article_id,
        "headline": f"h{article_id}",
        "summary": "s",
        "content": None,
        "author": "a",
        "created_at": created_at,
        "updated_at": created_at,
        "url": "https://example.com",
        "source": "TestWire",
        "symbols": [symbol],
        "images": [],
    }
    return FetchedArticle(raw=raw, article=Article(**raw))


def test_append_writes_raw_jsonl(tmp_path):
    store = NewsStore(tmp_path / "data")
    assert store.append("AAPL", fetched(1, "2026-10-02T10:00:00Z"))
    path = tmp_path / "data" / "articles" / "AAPL" / "2026-10-02.jsonl"
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["id"] == 1 and obj["headline"] == "h1"
    assert set(obj.keys()) == set(fetched(1, "2026-10-02T10:00:00Z").raw.keys())


def test_append_deduplicates_by_symbol_and_id(tmp_path):
    store = NewsStore(tmp_path / "data")
    assert store.append("AAPL", fetched(1, "2026-10-02T10:00:00Z"))
    assert not store.append("AAPL", fetched(1, "2026-10-02T11:00:00Z"))
    path = tmp_path / "data" / "articles" / "AAPL" / "2026-10-02.jsonl"
    assert len(path.read_text().splitlines()) == 1


def test_same_id_under_different_symbol_is_stored(tmp_path):
    store = NewsStore(tmp_path / "data")
    assert store.append("AAPL", fetched(1, "2026-10-02T10:00:00Z", "AAPL"))
    assert store.append("MSFT", fetched(1, "2026-10-02T10:00:00Z", "MSFT"))


def test_manifest_written_atomically_with_correct_fields(tmp_path):
    store = NewsStore(tmp_path / "data")
    store.append("AAPL", fetched(1, "2026-10-02T10:00:00Z"))
    store.append("AAPL", fetched(2, "2026-10-02T11:00:00Z"))
    manifest_path = tmp_path / "data" / "articles" / "AAPL" / "2026-10-02.jsonl.manifest.json"
    assert manifest_path.is_file()
    assert not (manifest_path.parent / "2026-10-02.jsonl.tmp").exists()
    m = json.loads(manifest_path.read_text())
    assert m["records"] == 2
    assert m["article_ids"] == [1, 2]
    assert m["first_created_at"] == "2026-10-02T10:00:00Z"
    assert m["last_created_at"] == "2026-10-02T11:00:00Z"
    assert len(m["sha256"]) == 64
    assert m["bytes"] > 0


def test_append_skips_out_of_order(tmp_path):
    store = NewsStore(tmp_path / "data")
    assert store.append("AAPL", fetched(1, "2026-10-02T11:00:00Z")) is True
    # Older article arriving late (overlapping poll window) is skipped, not stored.
    assert store.append("AAPL", fetched(2, "2026-10-02T10:00:00Z")) is False


def test_rejects_path_traversal_symbol(tmp_path):
    store = NewsStore(tmp_path / "data")
    with pytest.raises(StorageLayoutError):
        store.append("../../etc", fetched(1, "2026-10-02T10:00:00Z"))


def test_verify_passes_on_good_data(tmp_path):
    store = NewsStore(tmp_path / "data")
    store.append("AAPL", fetched(1, "2026-10-02T10:00:00Z"))
    store.append("AAPL", fetched(2, "2026-10-02T11:00:00Z"))
    assert store.verify() == []


def test_verify_fails_on_tampered_jsonl(tmp_path):
    store = NewsStore(tmp_path / "data")
    store.append("AAPL", fetched(1, "2026-10-02T10:00:00Z"))
    path = tmp_path / "data" / "articles" / "AAPL" / "2026-10-02.jsonl"
    with path.open("a") as f:
        f.write('{"id": 99}\n')
    errors = store.verify()
    assert any("sha256" in e for e in errors)


def test_verify_fails_on_duplicate_id(tmp_path):
    store = NewsStore(tmp_path / "data")
    store.append("AAPL", fetched(1, "2026-10-02T10:00:00Z"))
    path = tmp_path / "data" / "articles" / "AAPL" / "2026-10-02.jsonl"
    # Bypass append's dedup to simulate a corrupted file.
    with path.open("a") as f:
        f.write(path.read_text().splitlines()[0] + "\n")
    store._write_manifest(path)
    errors = store.verify()
    assert any("duplicate" in e for e in errors)


def test_verify_fails_on_out_of_order(tmp_path):
    store = NewsStore(tmp_path / "data")
    path = tmp_path / "data" / "articles" / "AAPL" / "2026-10-02.jsonl"
    path.parent.mkdir(parents=True)
    for aid, ts in ((1, "2026-10-02T11:00:00Z"), (2, "2026-10-02T10:00:00Z")):
        with path.open("a") as f:
            f.write(json.dumps(fetched(aid, ts).raw) + "\n")
    store._write_manifest(path)
    errors = store.verify()
    assert any("out-of-order" in e for e in errors)


def test_verify_fails_on_missing_manifest(tmp_path):
    store = NewsStore(tmp_path / "data")
    store.append("AAPL", fetched(1, "2026-10-02T10:00:00Z"))
    manifest = tmp_path / "data" / "articles" / "AAPL" / "2026-10-02.jsonl.manifest.json"
    manifest.unlink()
    assert any("missing manifest" in e for e in store.verify())


def test_verify_empty_store_ok(tmp_path):
    assert NewsStore(tmp_path / "data").verify() == []


def test_parse_day():
    assert str(parse_day("2026-10-02T10:00:00Z")) == "2026-10-02"
    with pytest.raises(StoreError):
        parse_day("not-a-date")


def test_created_at_date_routes_to_dated_file(tmp_path):
    store = NewsStore(tmp_path / "data")
    store.append("AAPL", fetched(1, "2026-10-03T01:00:00Z"))
    assert (tmp_path / "data" / "articles" / "AAPL" / "2026-10-03.jsonl").is_file()
