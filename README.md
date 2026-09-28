# StockFlow — 사내 재고관리

Excel로 관리하던 재고 시트를 업로드하면 표 구조를 자동으로 분석해 DB에 넣고,
웹에서 검색·수정·출고/입고 처리한 뒤 **원본 서식을 유지한 채 수정본 Excel로 다시 내보내는** Flask 앱입니다.

## 주요 기능

| 기능                  | 설명                                                                                                                                                                                                                 |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Excel 업로드          | 헤더 행 자동 감지, 병합 셀 보정, 시트별 표 인식. 원본 컬럼은 `data_json`에 그대로 보존                                                                                                                               |
| 검색 / 필터           | 전체 시트 통합 검색, 컬럼별 동적 필터, 정렬, 페이지네이션                                                                                                                                                            |
| 재고 수정             | 관리자가 셀 단위로 수정, 변경 이력(`InventoryChange`) 자동 기록                                                                                                                                                      |
| 출고 / 입고           | 출고 시 수량 차감(장애 티켓·현장 담당자·시리얼 기록), 재고가 `LOW_STOCK_THRESHOLD` 이하로 떨어지면 입고요청 자동 생성. 입고요청은 승인 → 물품도착(자동 입고) 흐름                                                    |
| 출고 취소 / 반납      | 잘못 출고한 건을 취소하면 수량이 원복되고 '출고취소 원복' 입고 이력이 남음 (관리자 또는 본인)                                                                                                                        |
| 시리얼 추적           | 입고·출고 때 적은 시리얼번호로 디스크 개체가 재고인지, 어느 사이트로 나갔는지, 이력까지 조회                                                                                                                         |
| 수정본 Excel 내보내기 | 업로드 당시 원본을 열어 DB 값만 덮어써서 서식·병합·열 너비 유지                                                                                                                                                      |
| 대시보드              | 저재고, **월별/년도별 × 사이트별 사용 디스크(코드·수량) + 전월/전년 동월 대비 증감**, **디스크 코드별 소비 추이·예상 소진 시점**, 최근 1년 TOP 10                                                                    |
| 사이트 상세           | 사이트 클릭 → 월별 출고, 코드별 누적, 최근 입출고, 진행 중 요청, 위치가 그 사이트인 보유 재고                                                                                                                        |
| 승인 대기 배지        | 미승인 입고요청 수를 사이드바에 빨간 배지로. `STOCKREQUEST_STALE_DAYS` 이상 방치된 건이 있으면 진한 색으로 깜빡임                                                                                                    |
| 이메일 알림 (Gmail)   | 입고요청 생성/저재고 → 관리자, 승인/입고완료 → 요청자                                                                                                                                                                |
| 계정 관리             | 내 계정(비밀번호 변경·이메일·담당 사이트 **여러 개**), 관리자 사용자 관리(역할·초기화·비활성화). 담당 사이트는 출고/입고/요청/시리얼 목록의 기본 범위('내 담당 사이트 / 개별 / 전체' 선택)와 출고·요청 모달의 선택지 |
| 활동 로그             | 모든 사용자의 출고·입고·요청·승인·도착·Excel·계정·로그인 기록                                                                                                                                                        |
| AI 채팅 (선택)        | Gemini가 DB 조회 결과만 근거로 답변. 수량 변경은 "제안 → 관리자 승인" 2단계                                                                                                                                          |
| eBay 가격 조회 (선택) | 품번으로 eBay Browse API 검색, 가격+배송비 총액 기준 정렬                                                                                                                                                            |

## 기술 스택

Python 3.12 · Flask 3 · Flask-SQLAlchemy · Flask-Login · Flask-WTF(CSRF) · Flask-Limiter · MySQL 8.4 · openpyxl · waitress · 바닐라 JS

## 빠른 시작

### 1. 환경변수

```bash
cp .env.example .env
```

`.env`에서 최소 다음 값을 채웁니다.

- `SECRET_KEY` — 16자 이상. 예시값(`CHANGE_ME`)이 그대로 있으면 **기동이 거부됩니다.**
  `python -c "import secrets; print(secrets.token_hex(32))"`
- `DATABASE_URL`, `MYSQL_*` — DB 접속 정보
- `ADMIN_PASSWORD` — Docker 첫 실행 때 만들 관리자 비밀번호 (8자 이상). `ADMIN_USERNAME`은 기본 `admin`입니다.
- (선택) `GEMINI_API_KEY`, `EBAY_APP_ID` / `EBAY_CERT_ID`

### 2-A. Docker로 실행 (권장)

```bash
docker compose up -d --build
# http://localhost:51000
```

MySQL과 앱이 함께 뜹니다. 업로드 파일과 로그는 각각 `uploads_data`, `logs_data` 볼륨에 저장됩니다.
DB에 관리자가 아직 없으면 `.env`의 `ADMIN_USERNAME` / `ADMIN_PASSWORD`로 초기 관리자 계정을 생성합니다. 기존 관리자 계정이나 비밀번호는 재시작해도 바뀌지 않습니다.

### 2-B. 로컬 Python으로 실행

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt

# MySQL만 컨테이너로
docker compose up -d mysql

python run.py                   # waitress, http://localhost:51000
# 개발 중 자동 리로드가 필요하면
FLASK_DEBUG=1 python run.py
```

### 2-C. MySQL 없이 바로 띄우기 (로컬 확인용)

```powershell
.\run_local.ps1          # SQLite(instance/stockflow.db) 로 기동, 관리자 admin / admin12345 자동 생성
.\run_local.ps1 -Debug   # 자동 리로드
```

`.env` 는 그대로 두고 이 프로세스에서만 `DATABASE_URL` 을 SQLite 로 덮어씁니다. 운영 데이터와 무관한 별도 DB 입니다.

### 3. 계정 생성

공개 회원가입은 없습니다. Docker의 초기 관리자는 `.env`의 `ADMIN_USERNAME`과 `ADMIN_PASSWORD`로 생성되고, 이후 관리자가 **사용자 추가** 메뉴에서 계정을 만듭니다. 기존 관리자 계정이 있는 DB에는 초기 계정을 추가하지 않습니다.

## 스키마 변경 (마이그레이션)

스키마는 Alembic(Flask-Migrate)으로 관리합니다. `AUTO_MIGRATE=1`(기본)이면 **앱이 기동할 때 자동으로 `flask db upgrade`를 실행**하므로 보통은 신경 쓸 일이 없습니다.

- **기존 운영 DB**(예전 `db.create_all()`로 만든 것)도 그대로 됩니다. `0001_baseline`은 이미 있는 테이블은 건너뛰고, `0002`가 새 컬럼/테이블만 추가합니다. `flask db stamp` 같은 사전 작업이 필요 없습니다.
- 수동으로 하려면:

```bash
set FLASK_APP=run.py            # Windows (macOS/Linux: export FLASK_APP=run.py)
flask db upgrade                # 최신으로
flask db current                # 현재 리비전
flask db downgrade 0001_baseline
```

- 모델을 바꿨을 때 새 마이그레이션 만들기: `flask db migrate -m "설명"` 후 `migrations/versions/` 에 생성된 파일을 검토하고 커밋.

## 운영 규칙 설정 (.env)

| 변수                            | 기본         | 의미                                                                |
| ------------------------------- | ------------ | ------------------------------------------------------------------- |
| `APP_TIMEZONE`                  | `Asia/Seoul` | 화면 표시·월별/일별 집계 기준 시간대. DB에는 UTC로 저장             |
| `LOW_STOCK_THRESHOLD`           | `1`          | 이 수량 이하면 저재고. 출고 후 이 값 이하가 되면 입고요청 자동 생성 |
| `STOCKREQUEST_STALE_DAYS`       | `3`          | 미승인 입고요청이 이 일수를 넘으면 배지·목록에서 '지연' 강조        |
| `SMTP_*`, `NOTIFY_ADMIN_EMAILS` | 비움         | Gmail 알림. 비워두면 알림만 건너뜁니다 (앱 동작에는 영향 없음)      |

### Gmail 알림 설정

1. Google 계정 → 보안 → **2단계 인증** 켜기
2. 같은 화면에서 **앱 비밀번호** 16자리 발급 (일반 비밀번호로는 로그인이 거부됩니다)
3. `.env`에 `SMTP_USER=본인@gmail.com`, `SMTP_PASSWORD=앱비밀번호`, `MAIL_FROM=StockFlow <본인@gmail.com>`
4. 관리자 계정의 **내 계정 → 이메일** 을 채우거나 `NOTIFY_ADMIN_EMAILS`에 나열

## 프로젝트 구조

```
app/
├─ __init__.py          앱 팩토리, 확장 초기화, 공통 에러 핸들러, 보안 헤더
├─ logging_config.py    app.log / error.log 회전 로그
├─ models/              User, ExcelFile/ExcelSheet/SheetColumn/DetectedTable,
│                       InventoryRow/InventoryGroup/InventoryChange,
│                       StockOut/StockIn/StockRequest/DiskUnit, ChatSession, AdminLog
├─ routes/
│  ├─ auth.py           로그인/로그아웃/사용자 추가(관리자)
│  ├─ pages.py          대시보드/사이트 상세/시리얼 페이지
│  ├─ stats.py          출고 통계 API (기간·비교·코드 추이·사이트 요약)
│  ├─ users.py          내 계정, 사용자 관리(관리자)
│  ├─ units.py          시리얼(DiskUnit) 조회 API
│  ├─ files.py          Excel 업로드/상세/삭제/내보내기
│  ├─ inventory.py      /api/search, /api/filters, /api/schema
│  ├─ sheets.py         행 조회/수정/삭제, 컬럼 추가
│  ├─ stockout.py       출고 / 출고 취소
│  ├─ stockin.py        입고
│  ├─ stockrequest.py   입고요청 승인/도착
│  ├─ ai.py             Gemini 채팅 + 변경 제안 적용
│  ├─ ebay.py           eBay 가격 조회
│  ├─ adminlog.py       활동 로그 (전 사용자)
│  └─ common.py         admin_required, log_action, set_row_quantity, lock_row, 시리얼 파싱
├─ services/
│  ├─ excel/parser.py   헤더 감지·표 추출
│  ├─ excel/exporter.py 수정본 Excel 생성
│  ├─ inventory/normalize.py  컬럼명 → 정규화 필드 매핑, 수량 파싱
│  ├─ notify/mail.py    Gmail SMTP 알림 (백그라운드 스레드)
│  └─ ebay/client.py    OAuth 토큰 캐시 + Browse API
├─ utils/time.py        UTC 저장 ↔ 로컬(KST) 표시, SQL 시간대 보정
├─ static/              css, js (페이지별 1파일)
└─ templates/           Jinja2 (layouts/base.html 상속)
migrations/             Alembic 마이그레이션 (0001 baseline, 0002 계정/시리얼/티켓, 0003 담당 사이트 복수)
tests/                  pytest (SQLite 메모리 DB, 126개; JS 문법은 node 없으면 내장 V8 로 검사)
run.py                  진입점 (waitress / FLASK_DEBUG=1 이면 개발 서버)
check_ebay_creds.py     eBay 키 형식 점검 스크립트
```

## 권한

- `user`: 조회, 출고(본인 출고 취소), 입고, 입고요청, 시리얼 조회, 내 계정
- `admin`: 위 전부 + Excel 업로드/삭제, 행 수정/삭제, 컬럼 추가, 입고요청 승인/도착, 모든 출고 취소, 사용자 관리, 활동 로그, AI 변경 적용

역할은 사용자 추가 화면에서 명시적으로 선택합니다.

## 보안 관련 설정

- 모든 POST/PATCH 요청에 CSRF 토큰 필요 (`X-CSRFToken` 헤더는 `static/js/app.js`가 자동으로 붙임)
- 로그인 시도 제한: IP당 1분 10회 / 1시간 100회 (`RATELIMIT_STORAGE_URI`)
- HTTPS 뒤에서 운영 시 `SESSION_COOKIE_SECURE=1`
- 로그에는 아이디/비밀번호/요청 본문을 남기지 않습니다. 장애 추적은 응답의 `X-Request-ID`(또는 JSON의 `request_id`)로 `logs/app.log`를 검색하세요.

## 개발

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
```

## 라이선스

사내 프로젝트.
