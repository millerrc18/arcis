"""I-16: nothing private is ever committed. Fails on tracked files that
look like data, oversized files, misnamed sprint files, or files containing
credential-shaped strings.

Usage: python tools/check_hygiene.py [repo-root]
Exits 0 when clean, 1 otherwise. A line ending in `# hygiene: allow`
(or `<!-- hygiene: allow -->` in Markdown) is skipped; each use must be
justified in the PR template.
"""
import re
import subprocess
import sys
from pathlib import Path

DATA_EXTENSIONS = {".jsonl", ".parquet", ".db", ".sqlite", ".gguf", ".safetensors", ".pkl", ".zip"}
MAX_BYTES = 1_000_000
SPRINT_PATTERN = re.compile(r"S\d\d-[a-z0-9-]+\.md")
ALLOW_PRAGMA = re.compile(r"(#|\<!--)\s*hygiene:\s*allow\s*(-->)?\s*$")

# (pattern, label). Written to avoid matching their own source text.
CREDENTIAL_PATTERNS = [
    (re.compile(r"\bPK[A-Z0-9]{20}\b"), "Alpaca-style key ID"),
    (
        re.compile(r"(?i)\b(api[_-]?secret|secret[_-]?key)\b\s*[:=]\s*['\"]?[\w\-.]{16,}"),
        "assigned secret value",
    ),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key block"),
    (
        re.compile(r"https?://\S*[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"),
        "URL containing a UUID (possible ping URL)",
    ),
]


def tracked_files(repo_root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=repo_root, capture_output=True, text=True, check=True
    )
    return [line for line in out.stdout.splitlines() if line]


def check(repo_root: Path, tracked: list[str] | None = None) -> list[str]:
    files = tracked if tracked is not None else tracked_files(repo_root)
    errors: list[str] = []
    for rel in sorted(files):
        path = repo_root / rel
        posix = rel.replace("\\", "/")
        if Path(rel).suffix in DATA_EXTENSIONS:
            errors.append(f"{rel}: data extension not allowed in the repo")
        if Path(rel).suffix == ".csv" and not (
            posix.startswith("config/") or posix.startswith("docs/research/")
        ):
            errors.append(f"{rel}: .csv only allowed under config/ or docs/research/")
        if path.is_file() and path.stat().st_size > MAX_BYTES:
            errors.append(f"{rel}: exceeds 1 MB")
        if posix.startswith("docs/sprints/") and not SPRINT_PATTERN.fullmatch(Path(rel).name):
            errors.append(f"{rel}: sprint file name must match SNN-slug.md")
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary; extension rules already cover data files
        if "\0" in text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if ALLOW_PRAGMA.search(line):
                continue
            for pattern, label in CREDENTIAL_PATTERNS:
                if pattern.search(line):
                    errors.append(f"{rel}:{i}: possible {label}")
                    break
    return errors


def main() -> int:
    repo = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    errors = check(repo)
    for e in errors:
        print(f"hygiene: {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
