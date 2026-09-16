import logging
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

logger = logging.getLogger(__name__)


def _write_value(cell, value):
    """DB JSON 값을 Excel 셀에 안전하게 기록한다."""
    # 병합 셀의 좌상단이 아닌 셀은 openpyxl에서 쓰기 금지다.
    if isinstance(cell, MergedCell):
        return

    if value is None:
        cell.value = None
        return

    # bool은 숫자로 변환하지 않는다.
    if isinstance(value, (bool, int, float)):
        cell.value = value
        return

    cell.value = str(value)


def export_excel(excel_file):
    """
    업로드 당시의 원본 Excel을 다시 열고 DB에 저장된 현재 행 데이터를
    같은 Sheet/행 위치에 반영하여 수정본을 메모리에서 생성한다.

    원본 파일의 서식/병합/열 너비 등은 가능한 한 그대로 유지하고,
    웹에서 수정된 데이터만 덮어쓴다.
    """
    source = Path(excel_file.file_path)
    logger.info("Export workbook load | file_id=%s | path=%s", excel_file.id, source)

    if not source.exists():
        raise FileNotFoundError(f"원본 Excel을 찾을 수 없습니다: {source}")

    keep_vba = source.suffix.lower() == ".xlsm"
    wb = load_workbook(source, keep_vba=keep_vba)
    logger.info(
        "Export workbook opened | file_id=%s | sheets=%s",
        excel_file.id,
        len(wb.sheetnames),
    )

    # SQLAlchemy relationship을 사용하면 이미 해당 파일의 모든 Sheet/Row가 연결되어 있다.
    for sheet in excel_file.sheets:
        if sheet.sheet_name not in wb.sheetnames:
            continue

        ws = wb[sheet.sheet_name]
        columns = sorted(sheet.columns, key=lambda c: (c.column_index or 0, c.id))
        rows = sorted(sheet.rows, key=lambda r: r.row_number or 0)

        # 웹에서 추가된 컬럼은 원본 마지막 컬럼 뒤에 생성한다.
        # 원본에 이미 존재하는 컬럼은 SheetColumn의 column_index를 그대로 사용한다.
        for column in columns:
            if not column.column_index:
                continue
            col_idx = int(column.column_index)
            header_row = None
            if column.table_id:
                table = next((t for t in sheet.tables if t.id == column.table_id), None)
                if table:
                    header_row = table.header_row
            if header_row:
                target = ws.cell(header_row, col_idx)
                if not isinstance(target, MergedCell) and target.value in (None, ""):
                    target.value = column.original_name

        for row in rows:
            if not row.row_number:
                continue

            data = row.data_json or {}

            if row.is_deleted:
                # 웹에서 삭제한 행은 데이터 영역만 비운다. 행 자체는 삭제하지 않아
                # 원본 서식과 행 번호가 깨지지 않게 한다.
                for column in columns:
                    if not column.column_index:
                        continue
                    target = ws.cell(row.row_number, int(column.column_index))
                    _write_value(target, None)
                continue

            for column in columns:
                if not column.column_index:
                    continue
                name = column.original_name
                if name in data:
                    _write_value(
                        ws.cell(row.row_number, int(column.column_index)),
                        data.get(name),
                    )

        # 추가 컬럼의 이름이 비어 있지 않도록 보정
        for column in columns:
            if column.column_index and column.table_id:
                table = next((t for t in sheet.tables if t.id == column.table_id), None)
                if table and table.header_row:
                    target = ws.cell(table.header_row, int(column.column_index))
                    if not isinstance(target, MergedCell):
                        target.value = column.original_name

        # 빈/병합 시트에서도 자동 필터 설정 자체가 오류를 만들지 않도록 방어한다.
        if ws.max_row > 0 and ws.max_column > 0:
            ws.auto_filter.ref = ws.dimensions

    output = BytesIO()
    wb.save(output)
    logger.info(
        "Export workbook saved | file_id=%s | bytes=%s",
        excel_file.id,
        output.getbuffer().nbytes,
    )
    output.seek(0)
    return output
