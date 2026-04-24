"""Base class for analytics results with serialization helpers."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from typing import Any


class AnalyticsResult:
    """Mixin providing to_dict() and to_rich_table() for analytics dataclasses.

    All analytics result types inherit from this.  Subclasses must also
    be ``@dataclass`` decorated.
    """

    def to_dict(self) -> dict[str, Any]:
        """Recursively convert to a JSON-serializable dict."""
        return _serialize(dataclasses.asdict(self))

    def to_rich_table(self) -> "rich.table.Table":
        """Render as a Rich Table for CLI output.  Override for custom layout."""
        from rich.table import Table

        table = Table(title=type(self).__name__)
        table.add_column("Field", style="cyan")
        table.add_column("Value")

        for field in dataclasses.fields(self):
            val = getattr(self, field.name)
            table.add_row(field.name, _format_value(val))
        return table


def _serialize(obj: Any) -> Any:
    """Recursively convert dataclass fields to JSON-safe types."""
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, float):
        if obj != obj:  # NaN check
            return None
        return obj
    return obj


def _format_value(val: Any) -> str:
    """Format a value for Rich table display."""
    if isinstance(val, float):
        if val != val:
            return "N/A"
        return f"{val:.4f}"
    if isinstance(val, list) and len(val) > 5:
        return f"[{len(val)} items]"
    return str(val)
