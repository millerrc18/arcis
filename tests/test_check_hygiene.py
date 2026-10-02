"""T3: the hygiene check fails on bad examples and passes on good ones.

Credential-shaped values are built dynamically so this file itself stays clean.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_hygiene


def make(tmp_path: Path, rel: str, content: str = "hello\n") -> str:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return rel


def test_fails_on_data_extension(tmp_path):
    rel = make(tmp_path, "out.jsonl")
    assert any("data extension" in e for e in check_hygiene.check(tmp_path, [rel]))


def test_fails_on_csv_outside_allowed_dirs(tmp_path):
    rel = make(tmp_path, "notes.csv")
    assert any(".csv" in e for e in check_hygiene.check(tmp_path, [rel]))


def test_passes_on_csv_under_config(tmp_path):
    rel = make(tmp_path, "config/universe.csv")
    assert check_hygiene.check(tmp_path, [rel]) == []


def test_fails_on_oversize_file(tmp_path):
    p = tmp_path / "big.txt"
    p.write_bytes(b"x" * (1_000_001))
    assert any("1 MB" in e for e in check_hygiene.check(tmp_path, ["big.txt"]))


def test_fails_on_bad_sprint_name(tmp_path):
    rel = make(tmp_path, "docs/sprints/notes.md")
    assert any("sprint file name" in e for e in check_hygiene.check(tmp_path, [rel]))


def test_passes_on_good_sprint_name(tmp_path):
    rel = make(tmp_path, "docs/sprints/S01-news-recorder.md")
    assert check_hygiene.check(tmp_path, [rel]) == []


def test_fails_on_key_id_shaped_string(tmp_path):
    rel = make(tmp_path, "keys.txt", "id=" + "PK" + "A" * 20 + "\n")
    assert any("key ID" in e for e in check_hygiene.check(tmp_path, [rel]))


def test_fails_on_private_key_block(tmp_path):
    rel = make(tmp_path, "key.pem", "-----BEGIN RSA PRIVATE KEY-----\n")
    assert any("private key" in e for e in check_hygiene.check(tmp_path, [rel]))


def test_pragma_skips_the_line(tmp_path):
    rel = make(tmp_path, "note.md", "id=" + "PK" + "A" * 20 + "  # hygiene: allow\n")
    assert check_hygiene.check(tmp_path, [rel]) == []


def test_passes_on_clean_file(tmp_path):
    rel = make(tmp_path, "clean.py", "print('hello')\n")
    assert check_hygiene.check(tmp_path, [rel]) == []
