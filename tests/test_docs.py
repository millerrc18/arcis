"""T2: the repository scaffold stays legible.

- Every Markdown document in the repo is listed in README.md's documentation map.
- The S01 documentation moves landed (new homes exist, root copies are gone).
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def repo_docs():
    return sorted(
        p.relative_to(REPO).as_posix()
        for p in REPO.rglob("*.md")
        if ".git/" not in p.as_posix()
    )


def is_covered(doc, readme):
    p = Path(doc)
    return (
        doc in readme
        or p.name in readme
        or (p.parent.as_posix() + "/") in readme
    )


def test_every_document_is_in_the_readme_map():
    readme = (REPO / "README.md").read_text()
    docs = [d for d in repo_docs() if d != "README.md"]  # a document need not list itself
    missing = [d for d in docs if not is_covered(d, readme)]
    assert not missing, f"documents missing from README.md: {missing}"


def test_sprint_and_research_files_moved():
    for new in [
        "docs/sprints/S01-news-recorder.md",
        "docs/sprints/S02-carry-forward-inventory.md",
        "docs/sprints/S03-pre-tag-power.md",
        "docs/research/RESEARCH-QUESTIONS.md",
        "docs/research/research-log.md",
        "docs/reference-architecture.md",
    ]:
        assert (REPO / new).is_file(), f"missing moved file: {new}"
    for old in [
        "S01-news-recorder.md",
        "S02-carry-forward-inventory.md",
        "S03-pre-tag-power.md",
        "RESEARCH-QUESTIONS.md",
        "research-log.md",
        "reference-architecture.md",
    ]:
        assert not (REPO / old).exists(), f"leftover root copy: {old}"


def test_root_documents_in_place():
    for name in ["SCOPE.md", "PREREGISTRATION.md", "README.md", "CLAUDE.md", "CHANGELOG.md"]:
        assert (REPO / name).is_file(), f"missing root document: {name}"
