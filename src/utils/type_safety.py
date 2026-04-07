"""Type coercion utilities for SQLite string-affinity handling.

SQLite's dynamic typing means any column can store strings even when the
schema says REAL or INTEGER.  These helpers handle the common case where
a numeric column returns a string (e.g., "25.3") or None.
"""


def safe_numeric(value, default=0, type_=float):
    """Coerce *value* to a numeric type.

    Handles strings ("25.3"), None, single-element tuples from fetchone()
    like ``(25.3,)``, and numpy scalars.

    Returns *type_(default)* when coercion fails.
    """
    if value is None:
        return type_(default)
    # Unwrap single-element sequences (e.g., (4800.0,) from fetchone)
    if isinstance(value, (tuple, list)) and len(value) == 1:
        value = value[0]
    try:
        return type_(value)
    except (ValueError, TypeError):
        return type_(default)
