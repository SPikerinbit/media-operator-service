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


def test_frozen_distribution_contains_the_runtime_version():
    import ast
    spec = ast.parse((ROOT / 'packaging' / 'media_operator.spec').read_text(encoding='utf-8'))
    # Exercise the data manifest itself, without running PyInstaller in unit tests.
    data = next(node.value for node in spec.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'datas' for target in node.targets))
    entries = eval(compile(ast.Expression(data), '<packaging data>', 'eval'), {'root': ROOT, 'str': str})
    assert (str(ROOT/'VERSION'), '.') in entries
    assert (str(ROOT/'app'/'stages'), 'app/stages') in entries
