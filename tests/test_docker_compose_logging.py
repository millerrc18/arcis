import pathlib
import yaml
import pytest


_COMPOSE_PATH = pathlib.Path(__file__).parent.parent / "docker-compose.yml"


def _get_pg_command():
    data = yaml.safe_load(_COMPOSE_PATH.read_text())
    services = data.get("services", {})
    pg_service = services.get("postgres", {})
    return pg_service.get("command", [])


def test_log_statement_all_flag_present():
    cmd = _get_pg_command()
    pairs = list(zip(cmd, cmd[1:]))
    assert ("-c", "log_statement=all") in pairs, (
        f"Expected '-c log_statement=all' consecutive pair in command list, got: {cmd}"
    )


def test_log_line_prefix_flag_present():
    cmd = _get_pg_command()
    pairs = list(zip(cmd, cmd[1:]))
    matching = [
        (a, b) for a, b in pairs
        if a == "-c" and b.startswith("log_line_prefix=")
    ]
    assert matching, (
        f"Expected '-c log_line_prefix=...' consecutive pair in command list, got: {cmd}"
    )
