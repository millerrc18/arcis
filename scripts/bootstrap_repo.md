# Bootstrap checklist

1. Create GitHub repo
2. Upload contents of this starter pack
3. Create virtual environment: `python -m venv .venv && .venv/Scripts/activate` (Windows) or `source .venv/bin/activate` (macOS/Linux)
4. Install requirements: `pip install -r requirements.txt`
5. Copy `config/settings.example.yaml` to `config/settings.local.yaml` and edit values for your environment
6. Create `.env` with API secrets (see `config/settings.example.yaml` header for the full list)
7. Initialize DB with `python -m src.main init-db`
8. Run preflight check: `python -m src.main preflight`
9. Launch system: `python -m src.main startup`
