"""의존성 설치 전에도 실행할 수 있는 최소 정적 smoke test."""

import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_python_files_compile():
    for path in [ROOT / "run.py", *ROOT.glob("app/**/*.py")]:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_javascript_syntax():
    """
    node 가 있으면 `node --check`, 없으면 mini-racer(내장 V8) 로 `new Function(src)` 파싱을 시켜
    문법을 검사한다. 예전엔 node 가 없으면 조용히 건너뛰어 템플릿 리터럴 백틱이 빠진 파일이 그대로 통과했다.
    """
    files = sorted((ROOT / "app/static/js").glob("*.js"))
    assert files

    if shutil.which("node"):
        for path in files:
            result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
            assert result.returncode == 0, f"{path.name}: {result.stderr}"
        return

    py_mini_racer = pytest.importorskip("py_mini_racer")
    racer = py_mini_racer.MiniRacer()
    for path in files:
        src = path.read_text(encoding="utf-8")
        # 실행하지 않고 파싱만 — SyntaxError 면 JSSyntaxError/JSParseException 으로 올라온다
        try:
            racer.eval("new Function(" + json.dumps(src) + ")")
        except Exception as exc:
            pytest.fail(f"{path.name}: {str(exc).splitlines()[0]}")
