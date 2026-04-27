"""Jinja2 template configuration -- singleton imported by route modules."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))
