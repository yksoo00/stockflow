"""의존성 설치 전에도 실행할 수 있는 최소 정적 smoke test."""

import ast
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_python_files_compile():
    for path in [ROOT / "run.py", *ROOT.glob("app/**/*.py")]:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


@pytest.mark.skipif(shutil.which("node") is None, reason="node 가 설치되어 있지 않음")
def test_javascript_syntax():
    for path in (ROOT / "app/static/js").glob("*.js"):
        result = subprocess.run(
            ["node", "--check", str(path)], capture_output=True, text=True
        )
        assert result.returncode == 0, f"{path.name}: {result.stderr}"
