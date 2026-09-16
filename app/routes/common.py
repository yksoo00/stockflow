import logging
import os
from functools import wraps

from flask import flash, jsonify, redirect, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import AdminLog, DiskUnit, ExcelSheet, InventoryRow, SheetColumn
from ..models.user import parse_site_list
from ..services.inventory.normalize import find_quantity_key, normalize_row
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


def low_stock_filter(query):
    """수량이 임계값 이하이고 용량 정보가 있는(=디스크로 보이는) 행만."""
    return query.filter(
        InventoryRow.is_deleted == False,  # noqa: E712
        InventoryRow.quantity.isnot(None),
        InventoryRow.quantity <= low_stock_threshold(),
        InventoryRow.capacity.isnot(None),
        InventoryRow.capacity != "",
    )


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
