"""The product version has one source: the VERSION file at the repository root."""
import json
from pathlib import Path

from app.version import VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_version_file_is_the_only_source():
    assert VERSION == (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))["version"] == VERSION
    iss = (ROOT / "packaging" / "MediaOperator.iss").read_text(encoding="utf-8")
    assert f'#define AppVersion "{VERSION}"' in iss
    sidebar = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
    assert "__APP_VERSION__" in sidebar
    assert "1.1.0" not in (ROOT / "app" / "main.py").read_text(encoding="utf-8")
