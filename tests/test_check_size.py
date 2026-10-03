"""T3: the size check fails on bad examples and passes on good ones."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_size


def write(tmp_path: Path, name: str, lines: int, func_lines: int | None = None) -> Path:
    p = tmp_path / name
    if func_lines is None:
        p.write_text("x = 1\n" * lines)
    else:
        # def line + (func_lines - 2) body lines + return line == func_lines total
        body = "".join(f"    y = {i}\n" for i in range(func_lines - 2))
        text = f"def f():\n{body}    return y\n"
        text += "z = 2\n" * max(0, lines - func_lines)
        p.write_text(text)
    return p


def test_fails_on_function_over_60_lines(tmp_path):
    write(tmp_path, "big.py", lines=70, func_lines=61)
    errors = check_size.check(tmp_path)
    assert any("61 lines" in e for e in errors)


def test_passes_on_function_at_60_lines(tmp_path):
    write(tmp_path, "ok.py", lines=70, func_lines=60)
    assert check_size.check(tmp_path) == []


def test_fails_on_file_over_400_lines(tmp_path):
    write(tmp_path, "long.py", lines=401)
    errors = check_size.check(tmp_path)
    assert any("401 lines" in e for e in errors)


def test_passes_on_small_file(tmp_path):
    write(tmp_path, "small.py", lines=10)
    assert check_size.check(tmp_path) == []
