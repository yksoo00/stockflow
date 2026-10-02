"""Excel 업로드/내보내기/삭제 — 실제 xlsx 를 만들어 파서→DB→exporter 를 통과시킨다."""

import io

from openpyxl import Workbook, load_workbook

from app import db
from app.models import DiskUnit, ExcelFile, InventoryGroup, InventoryRow, SheetColumn, StockOut

from .conftest import api


def _xlsx(rows, header_row_offset=0, title_rows=()):
    """
    rows[0] 이 헤더. header_row_offset 만큼 위에 제목 행을 둔다.
    빈 열(None 헤더 + 데이터 없음)을 섞어 B-15 시나리오를 만든다.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "재고"
    for t in title_rows:
        ws.append(t)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _upload(client, buf, name="inv.xlsx", allow_duplicate=False):
    data = {"file": (buf, name), "csrf_token": client.csrf}
    if allow_duplicate:
        data["allow_duplicate"] = "1"
    return client.post("/upload", data=data, content_type="multipart/form-data", follow_redirects=False)


# 헤더: A=Code, B=(빈 열), C=품명, D=수량, E=용량, F=위치
ROWS = [
    ["Code", None, "품명", "수량", "용량", "위치"],
    ["ST4000", None, "4TB SAS", 5, "4TB", "서울IDC"],
    ["ST8000", None, "8TB SATA", 1, "8TB", "부산DC"],
    [None, None, "품번없음", 2, None, None],
]


def test_upload_parses_and_keeps_real_column_index(admin_client, app):
    resp = _upload(admin_client, _xlsx(ROWS, title_rows=[["2026년 재고 현황", None, None, None, None, None]]))
    assert resp.status_code == 302, resp.get_data(as_text=True)
    assert resp.headers["Location"].startswith("/files/")

    with app.app_context():
        ef = ExcelFile.query.one()
        assert ef.processing_status == "completed"
        rows = InventoryRow.query.order_by(InventoryRow.row_number).all()
        assert len(rows) == 3
        assert rows[0].identifier == "ST4000" and rows[0].quantity == 5 and rows[0].location == "서울IDC"

        # 빈 B열은 건너뛰고, 품명은 실제 C(3)열, 수량은 D(4)열 이어야 한다 (예전엔 2,3 으로 밀렸다)
        cols = {c.original_name: c.column_index for c in SheetColumn.query.all()}
        assert cols == {"Code": 1, "품명": 3, "수량": 4, "용량": 5, "위치": 6}

        # 그룹 키는 해시(64자) — 512자 초과로 터지던 문제 (B-12)
        for g in InventoryGroup.query.all():
            assert len(g.group_key) == 64
        # 정규화 필드가 하나도 없는 행(품번없음, 용량 없음)도 그룹이 생겨야 한다
        assert InventoryGroup.query.count() == 3


def test_export_writes_edited_values_to_correct_cells(admin_client, app):
    _upload(admin_client, _xlsx(ROWS))

    with app.app_context():
        row = InventoryRow.query.filter_by(identifier="ST4000").one()
        row_id, file_id = row.id, row.excel_file_id

    # 웹에서 수량 5 → 4 로 수정
    resp = api(admin_client, "PATCH", f"/api/rows/{row_id}", data={"수량": 4, "위치": "대전DC"})
    assert resp.status_code == 200, resp.get_json()

    export = admin_client.get(f"/files/{file_id}/export")
    assert export.status_code == 200
    wb = load_workbook(io.BytesIO(export.data))
    ws = wb["재고"]
    # 헤더 다음 첫 데이터 행(2): A=Code, C=품명, D=수량, F=위치
    assert ws["A2"].value == "ST4000"
    assert ws["B2"].value is None  # 빈 열은 그대로 비어 있어야 한다
    assert ws["C2"].value == "4TB SAS"
    assert ws["D2"].value == 4
    assert ws["F2"].value == "대전DC"


def test_duplicate_upload_is_blocked_unless_overridden(admin_client, app):
    assert _upload(admin_client, _xlsx(ROWS)).status_code == 302

    dup = _upload(admin_client, _xlsx(ROWS), name="again.xlsx")
    assert dup.status_code == 302
    assert "duplicate_of=" in dup.headers["Location"]
    with app.app_context():
        assert ExcelFile.query.count() == 1
        assert InventoryRow.query.count() == 3  # 두 배가 되지 않았다

    forced = _upload(admin_client, _xlsx(ROWS), name="again.xlsx", allow_duplicate=True)
    assert forced.headers["Location"].startswith("/files/")
    with app.app_context():
        assert ExcelFile.query.count() == 2


def test_delete_file_with_stock_history_keeps_history(admin_client, app):
    _upload(admin_client, _xlsx(ROWS))
    with app.app_context():
        row = InventoryRow.query.filter_by(identifier="ST4000").one()
        row_id, file_id = row.id, row.excel_file_id

    # 출고(시리얼 포함) + 입고 + 입고요청 이력을 만든다 → 예전엔 FK 때문에 삭제가 500 이었다 (B-16)
    api(admin_client, "POST", "/api/stockout", row_id=row_id, site="A", quantity=1, serials="H-1")
    api(admin_client, "POST", "/api/stockin", row_id=row_id, quantity=1)
    api(admin_client, "POST", "/api/stockrequest", row_id=row_id, site="A", quantity=1)

    resp = admin_client.post(f"/files/{file_id}/delete", data={"csrf_token": admin_client.csrf})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/files")

    with app.app_context():
        assert ExcelFile.query.count() == 0
        assert InventoryRow.query.count() == 0
        assert InventoryGroup.query.count() == 0  # 행이 없어진 그룹은 정리
        out = StockOut.query.one()
        assert out.inventory_row_id is None and out.identifier == "ST4000"  # 이력은 스냅샷으로 남는다
        assert DiskUnit.query.one().inventory_row_id is None


def test_invalid_file_gives_friendly_error(admin_client):
    resp = _upload(admin_client, io.BytesIO(b"not an excel file"), name="bad.xlsx", )
    assert resp.status_code == 302
    # flash 는 <script id="flash-data"> 안에 JSON(유니코드 이스케이프)으로 들어간다
    with admin_client.session_transaction() as sess:
        messages = [m for _, m in sess.get("_flashes", [])]
    assert any("올바른 xlsx/xlsm 파일이 아니거나" in m for m in messages), messages


def test_export_logs_action(admin_client, app):
    _upload(admin_client, _xlsx(ROWS))
    with app.app_context():
        file_id = ExcelFile.query.one().id
    admin_client.get(f"/files/{file_id}/export")
    data = admin_client.get("/api/adminlog?action=excel_export").get_json()
    assert data["count"] == 1


def test_export_without_original_file_falls_back_to_db_data(admin_client, app):
    """원본 xlsx 가 서버에서 사라졌어도 DB 값으로 Excel 을 만들어 내려준다 (예전엔 404 JSON)."""
    from pathlib import Path

    _upload(admin_client, _xlsx(ROWS))
    with app.app_context():
        ef = ExcelFile.query.one()
        file_id = ef.id
        Path(ef.file_path).unlink()
        row_id = InventoryRow.query.filter_by(identifier="ST4000").one().id
    api(admin_client, "PATCH", f"/api/rows/{row_id}", data={"수량": 3})

    export = admin_client.get(f"/files/{file_id}/export")
    assert export.status_code == 200, export.get_data(as_text=True)[:200]
    assert "attachment" in export.headers["Content-Disposition"]

    ws = load_workbook(io.BytesIO(export.data))["재고"]
    assert [c.value for c in ws[1]] == ["Code", "품명", "수량", "용량", "위치"]
    assert [c.value for c in ws[2]] == ["ST4000", "4TB SAS", 3, "4TB", "서울IDC"]
    assert ws.max_row == 4  # 헤더 + 3행


def test_reupload_restores_missing_original_and_export_keeps_format(admin_client, app):
    """
    같은 DB 를 쓰는 다른 서버(로컬 ↔ Docker)에서 올려 원본이 이 서버에 없을 때,
    원본을 다시 올리면 중복으로 막지 않고 기존 기록에 원본을 붙여 서식 유지 내보내기가 되게 한다.
    """
    from pathlib import Path

    title = [["2026년 재고 현황", None, None, None, None, None]]
    _upload(admin_client, _xlsx(ROWS, title_rows=title))
    with app.app_context():
        ef = ExcelFile.query.one()
        file_id = ef.id
        Path(ef.file_path).unlink()
        row_id = InventoryRow.query.filter_by(identifier="ST4000").one().id
    api(admin_client, "PATCH", f"/api/rows/{row_id}", data={"수량": 3})

    resp = _upload(admin_client, _xlsx(ROWS, title_rows=title), name="원본.xlsx")
    assert resp.status_code == 302
    assert resp.headers["Location"] == f"/files/{file_id}"

    with app.app_context():
        assert ExcelFile.query.count() == 1  # 새 기록을 만들지 않는다
        assert InventoryRow.query.count() == 3  # 웹에서 고친 DB 값은 그대로
        assert Path(db.session.get(ExcelFile, file_id).file_path).is_file()

    export = admin_client.get(f"/files/{file_id}/export")
    assert export.status_code == 200
    assert "%EC%9B%90%EB%B3%B8%EC%84%9C%EC%8B%9D%EC%97%86%EC%9D%8C" not in export.headers["Content-Disposition"]  # (원본서식없음) 아님
    ws = load_workbook(io.BytesIO(export.data))["재고"]
    assert ws["A1"].value == "2026년 재고 현황"  # 원본 제목 행 유지
    assert ws["A3"].value == "ST4000" and ws["D3"].value == 3  # 수정값 반영
    assert "excel_restore" in [a["action"] for a in admin_client.get("/api/adminlog").get_json()["items"]]


def test_duplicate_upload_with_existing_original_is_still_blocked(admin_client, app):
    _upload(admin_client, _xlsx(ROWS))
    resp = _upload(admin_client, _xlsx(ROWS), name="again.xlsx")
    assert "duplicate_of=" in resp.headers["Location"]
    with app.app_context():
        assert ExcelFile.query.count() == 1


def test_delete_from_file_list_page_passes_csrf(admin_client, app):
    """목록(/files) 화면의 삭제 form 이 CSRF 토큰을 실어 보내야 한다 (예전엔 빠져서 400)."""
    import re

    _upload(admin_client, _xlsx(ROWS))
    with app.app_context():
        file_id = ExcelFile.query.one().id

    html = admin_client.get("/files").get_data(as_text=True)
    form = re.search(rf'<form method="post" action="/files/{file_id}/delete".*?</form>', html, re.S).group(0)
    token = re.search(r'name="csrf_token" value="([^"]+)"', form)
    assert token, form

    resp = admin_client.post(f"/files/{file_id}/delete", data={"csrf_token": token.group(1)})
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/files")
    with app.app_context():
        assert ExcelFile.query.count() == 0
