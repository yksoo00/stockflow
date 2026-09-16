# 로컬 개발용 실행 스크립트 — MySQL 없이 SQLite 파일 DB(instance/stockflow.db)로 띄운다.
# .env 의 DATABASE_URL 은 건드리지 않고 이 프로세스에서만 덮어쓴다.
#   .\run_local.ps1            → http://localhost:8000
#   .\run_local.ps1 -Debug     → Flask 개발 서버(자동 리로드)
param([switch]$Debug)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
New-Item -ItemType Directory -Force "$root\instance" | Out-Null

$env:DATABASE_URL = "sqlite:///$($root -replace '\','/')/instance/stockflow.db"
$env:LOG_CONSOLE = "1"
if ($Debug) { $env:FLASK_DEBUG = "1" }

if (-not (Test-Path "$root\.venv\Scripts\python.exe")) {
    Write-Host "가상환경이 없습니다: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt" -ForegroundColor Yellow
    exit 1
}

# 첫 실행이면 관리자 계정을 하나 만든다 (admin / admin12345 — 로그인 후 '내 계정'에서 바꾸세요)
& "$root\.venv\Scripts\python.exe" -c @"
from app import create_app, db
from app.models import User
from werkzeug.security import generate_password_hash
app = create_app()
with app.app_context():
    if not User.query.filter_by(username='admin').first():
        db.session.add(User(username='admin', name='관리자', role='admin', password_hash=generate_password_hash('admin12345')))
        db.session.commit()
        print('>> 관리자 계정 생성: admin / admin12345')
"@

& "$root\.venv\Scripts\python.exe" run.py
