from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("ASHARE_DATA_DIR", ROOT / "data")).expanduser().resolve()
BARS_DIR = DATA_DIR / "bars"
SKILLS_DIR = DATA_DIR / "skills"
RESULTS_DIR = DATA_DIR / "results"
DB_PATH = DATA_DIR / "market.sqlite3"
SEED_LIST = Path(os.getenv("ASHARE_SEED_LIST", DATA_DIR / "seed_stock_list.json")).expanduser()
DSH_BASE_URL = os.getenv("ASHARE_DSH_URL", "http://127.0.0.1:3080").rstrip("/")

for directory in (DATA_DIR, BARS_DIR, SKILLS_DIR, RESULTS_DIR):
    directory.mkdir(parents=True, exist_ok=True)
