"""Product version. The repository root VERSION file is the source of truth."""
from pathlib import Path

VERSION = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
