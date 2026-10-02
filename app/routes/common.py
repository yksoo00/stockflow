import logging
import os
from functools import wraps

from flask import flash, jsonify, redirect, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import AdminLog, DiskUnit, ExcelSheet, InventoryRow, SheetColumn
from ..models.user import parse_site_list
from ..services.inventory.normalize import (
    REQUIRED_QUANTITY_COLUMN,
    find_quantity_key,
    infer_field,
    normalize_row,
    to_number,
)
from ..utils.time import fmt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 저재고 기준 (B-25): 한 곳에서만 정의한다. 환경변수로 임계값 조정 가능.
# ---------------------------------------------------------------------------
def low_stock_threshold():
    try:
        return float(os.getenv("LOW_STOCK_THRESHOLD", "1"))
    except ValueError:
        return 1.0


def default_required_quantity():
    """
    필수수량 칸이 비어 있을 때의 기본값 = 예전 전역 기준(임계값 1 → 2개로 채움)과 같은 값.
    """
    return low_stock_threshold() + 1


def required_quantity_of(row):
    if row.required_quantity is not None:
        return row.required_quantity
    return default_required_quantity()


def low_stock_filter(query):
    """수량이 필수수량보다 적고 용량 정보가 있는(=디스크로 보이는) 행만."""
    return query.filter(
        InventoryRow.is_deleted == False,  # noqa: E712
        InventoryRow.quantity.isnot(None),
        InventoryRow.quantity
        < db.func.coalesce(InventoryRow.required_quantity, default_required_quantity()),
        InventoryRow.capacity.isnot(None),
        InventoryRow.capacity != "",
    )


def ensure_required_column(sheet):
    """
    시트에 필수수량 열이 없으면 맨 끝 열로 만들고, 빈 칸은 기본값으로 채운다.
    시트 화면에 보이고 그 자리에서 고칠 수 있게 하기 위함이다. 행이 없는 시트는 건드리지 않는다.
    """
    rows = InventoryRow.query.filter_by(sheet_id=sheet.id, is_deleted=False).all()
    if not rows:
        return

    columns = SheetColumn.query.filter_by(sheet_id=sheet.id).all()
    column = next(
        (c for c in columns if infer_field(c.original_name or "") == "required_quantity"), None
    )
    if column is None:
        # table_id 가 있어야 내보내기 때 헤더 행에 열 이름이 써진다.
        table_ids = [c.table_id for c in columns if c.table_id]
        column = SheetColumn(
            sheet_id=sheet.id,
            table_id=min(table_ids) if table_ids else rows[0].table_id,
            column_index=max([c.column_index or 0 for c in columns] or [0]) + 1,
            original_name=REQUIRED_QUANTITY_COLUMN,
            normalized_name="required_quantity",
            data_type="number",
            filter_type="range",
        )
        db.session.add(column)

    default = default_required_quantity()
    default_cell = int(default) if float(default).is_integer() else default
    for row in rows:
        value = to_number((row.data_json or {}).get(column.original_name))
        if value is None:
            data = dict(row.data_json or {})
            data[column.original_name] = default_cell
            row.data_json = data
            value = default
        row.required_quantity = value


def schema_columns(file_id=None, sheet_id=None, sheet_ids=None):
    query = SheetColumn.query
    if sheet_ids:
        query = query.filter(SheetColumn.sheet_id.in_(sheet_ids))
    elif sheet_id:
        query = query.filter_by(sheet_id=sheet_id)
    elif file_id:
        query = query.join(ExcelSheet, SheetColumn.sheet_id == ExcelSheet.id).filter(
            ExcelSheet.excel_file_id == file_id
        )

    columns = query.order_by(SheetColumn.column_index, SheetColumn.id).all()
    seen = set()
    result = []
    for column in columns:
        if column.original_name and column.original_name not in seen:
            seen.add(column.original_name)
            result.append(column.original_name)
    return result


def serialize_row(row):
    return {
        "id": row.id,
        "file_id": row.excel_file_id,
        "file_name": row.excel_file.original_filename if row.excel_file else None,
        "sheet_id": row.sheet_id,
        "row_number": row.row_number,
        "quantity": row.quantity,
        "identifier": row.identifier,
        "item_name": row.item_name,
        "manufacturer": row.manufacturer,
        "model": row.model,
        "capacity": row.capacity,
        "location": row.location,
        "status": row.status,
        "data": row.data_json,
    }


def parse_id_list(value):
    if not value:
        return []
    result = []
    for item in str(value).split(","):
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if value > 0:
            result.append(value)
    return list(dict.fromkeys(result))


def user_label(user):
    """처리자 표시명. user 가 None(삭제/미기록)이면 None. (B-21 우선순위 버그 대체)"""
    if not user:
        return None
    return user.name or user.username


def fmt_qty(value):
    """3.0 → '3', 2.5 → '2.5'"""
    if value is None:
        return ""
    value = float(value)
    return str(int(value)) if value.is_integer() else f"{value:g}"


def admin_required(view):
    """
    관리자(role == 'admin')만 접근 가능하도록 제한하는 데코레이터 (페이지용).
    로그인 검사까지 함께 처리하므로 @login_required와 중복으로 붙일 필요 없다.
    권한이 없으면 대시보드로 되돌려보낸다.
    """

    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "admin":
            flash("관리자만 사용할 수 있는 기능입니다.", "error")
            return redirect(url_for("main.dashboard"))
        return view(*args, **kwargs)

    return wrapped


def admin_required_api(view):
    """
    관리자(role == 'admin')만 호출 가능하도록 제한하는 데코레이터 (JSON API용).
    페이지 리다이렉트가 아니라 JSON 403을 돌려줌 — fetch로 호출하는 엔드포인트에만 쓴다.
    """

    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != "admin":
            return jsonify({"error": "관리자만 수정할 수 있습니다."}), 403
        return view(*args, **kwargs)

    return wrapped


# ---------------------------------------------------------------------------
# 활동 로그: 관리자뿐 아니라 모든 사용자의 출고/입고/요청/수정 등을 한 곳에 남긴다.
# ---------------------------------------------------------------------------
def log_action(action, detail=None, target_type=None, target_id=None, user_id=None):
    """
    활동 로그 한 줄 추가. db.session.commit()은 호출하는 쪽에서 기존 커밋과 함께 한다(여기서는 add만).
    user_id 를 넘기지 않으면 현재 로그인 사용자. (로그인 실패 등 비로그인 상황은 user_id=None)
    """
    if user_id is None and current_user.is_authenticated:
        user_id = current_user.id

    db.session.add(
        AdminLog(
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
        )
    )


# 예전 이름 호환
log_admin_action = log_action


# ---------------------------------------------------------------------------
# 재고 행 수량 갱신 공통 로직
# ---------------------------------------------------------------------------
def set_row_quantity(row, new_qty):
    """
    InventoryRow.quantity 와 data_json 의 수량 컬럼을 함께 바꾸고,
    정규화 필드를 재계산한 뒤 소속 InventoryGroup 합계까지 맞춘다 (B-18).
    """
    row.quantity = new_qty

    data = dict(row.data_json or {})
    qty_key = find_quantity_key(data)
    if qty_key:
        data[qty_key] = new_qty
        row.data_json = data

        n = normalize_row(data)
        row.identifier = n.get("identifier", row.identifier)
        row.item_name = n.get("item_name", row.item_name)
        row.manufacturer = n.get("manufacturer", row.manufacturer)
        row.model = n.get("model", row.model)
        row.capacity = n.get("capacity", row.capacity)
        row.required_quantity = n.get("required_quantity", row.required_quantity)
        row.location = n.get("location", row.location)
        row.status = n.get("status", row.status)

    sync_group_quantity(row.group)


def sync_group_quantity(group):
    """그룹 수량 = 소속 행(삭제되지 않은)의 quantity 합계."""
    if group is None:
        return
    total = (
        db.session.query(db.func.coalesce(db.func.sum(InventoryRow.quantity), 0.0))
        .filter(
            InventoryRow.inventory_group_id == group.id,
            InventoryRow.is_deleted == False,  # noqa: E712
        )
        .scalar()
    )
    group.quantity = float(total or 0)


def lock_row(row_id):
    """
    수량을 바꾸기 전 행을 잠근다 (B-19, 동시 출고로 음수 재고 방지).
    SQLite 는 행 잠금이 없어 with_for_update 가 무시되지만 트랜잭션 단위로는 직렬화된다.
    소프트 삭제된 행은 없는 것으로 취급한다.
    """
    row = (
        db.session.query(InventoryRow)
        .filter(InventoryRow.id == row_id)
        .with_for_update()
        .first()
    )
    if row is None or row.is_deleted:
        return None
    return row


def claim_transition(model, obj_id, *conditions, **values):
    """
    conditions 를 만족할 때만 values 로 바꾸는 원자적 UPDATE. 바꿨으면 True.

    "상태 확인 → 수량 반영" 사이에 같은 요청이 한 번 더 들어와 둘 다 통과하는 것을 막는다
    (물품도착/출고 취소 더블클릭). 조건 검사와 변경이 한 문장이라 MySQL·SQLite 모두에서
    먼저 들어온 쪽만 1행을 바꾸고, 뒤쪽은 커밋을 기다렸다가 0행이 된다.
    실패 경로에서는 반드시 rollback 해서 선점을 풀어야 한다.
    """
    changed = (
        db.session.query(model)
        .filter(model.id == obj_id, *conditions)
        .update(values, synchronize_session=False)
    )
    return changed == 1


# ---------------------------------------------------------------------------
# 사이트 필터 (목록 API 공통)
#   site  = 부분 일치 한 개 (검색창)
#   sites = 쉼표 구분 여러 개, 각각 부분 일치 OR (담당 사이트 여러 개일 때)
#   scope = "mine" 이면 로그인 사용자의 담당 사이트 전체
# ---------------------------------------------------------------------------
def apply_site_filter(query, column, args):
    site = (args.get("site") or "").strip()
    sites = parse_site_list(args.get("sites"))
    if args.get("scope") == "mine" and current_user.is_authenticated:
        sites = sites or current_user.site_list

    if site:
        return query.filter(column.ilike(f"%{site}%"))
    if sites:
        return query.filter(db.or_(*[column.ilike(f"%{s}%") for s in sites]))
    return query


# ---------------------------------------------------------------------------
# 시리얼번호
# ---------------------------------------------------------------------------
def parse_serials(raw):
    """
    줄바꿈/쉼표/공백으로 구분된 시리얼 문자열 → 중복 제거된 리스트.
    빈 값이면 [].
    """
    if not raw:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        items = str(raw).replace(",", "\n").replace(";", "\n").split()
    seen = []
    for item in items:
        s = str(item).strip()
        if s and s not in seen:
            seen.append(s)
    return seen


def serial_snapshot(serials):
    return "\n".join(serials) if serials else None


def serialize_unit(unit):
    return {
        "id": unit.id,
        "serial": unit.serial,
        "identifier": unit.identifier,
        "item_name": unit.item_name,
        "row_id": unit.inventory_row_id,
        "status": unit.status,
        "status_label": "재고" if unit.status == DiskUnit.STATUS_IN_STOCK else "출고",
        "site": unit.site,
        "stock_in_id": unit.stock_in_id,
        "stock_out_id": unit.stock_out_id,
        "created_at": fmt(unit.created_at),
        "updated_at": fmt(unit.updated_at),
    }
