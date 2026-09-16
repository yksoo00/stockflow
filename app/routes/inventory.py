import json
import logging
import re

from flask import Blueprint, jsonify, request
from flask_login import login_required
from sqlalchemy import Text, cast, or_

from .. import db
from ..models import ExcelFile, ExcelSheet, InventoryRow, SheetColumn
from .common import low_stock_filter, parse_id_list, schema_columns, serialize_row

api_bp = Blueprint("api", __name__)
logger = logging.getLogger(__name__)


def _selected_sheet_ids():
    return parse_id_list(request.args.get("sheet_ids"))


def _apply_scope(query, file_id=None, sheet_id=None, sheet_ids=None):
    """Apply Excel/Sheet scope. Empty sheet_ids means all sheets in scope."""
    if sheet_ids:
        query = query.filter(InventoryRow.sheet_id.in_(sheet_ids))
    elif sheet_id:
        query = query.filter(InventoryRow.sheet_id == sheet_id)
    elif file_id:
        query = query.filter(InventoryRow.excel_file_id == file_id)
    return query


@api_bp.get("/search")
@login_required
def search():
    low_only = request.args.get("low", "").strip() == "1"
    logger.info(
        "Inventory search | file_id=%s | sheet_ids=%s | q_present=%s | low_only=%s",
        request.args.get("file_id"),
        request.args.get("sheet_ids"),
        bool(request.args.get("q", "").strip()),
        low_only,
    )
    q = request.args.get("q", "").strip()
    file_id = request.args.get("file_id", type=int)
    sheet_id = request.args.get("sheet_id", type=int)
    sheet_ids = _selected_sheet_ids()
    page = max(request.args.get("page", 1, type=int), 1)
    page_size = min(max(request.args.get("page_size", 10, type=int), 1), 200)
    sort_col = request.args.get("sort", "").strip()
    sort_dir = request.args.get("dir", "desc").strip().lower()
    sort_dir = "asc" if sort_dir == "asc" else "desc"

    try:
        filters = json.loads(request.args.get("filters", "{}") or "{}")
        if not isinstance(filters, dict):
            filters = {}
    except (TypeError, ValueError, json.JSONDecodeError):
        filters = {}

    query = InventoryRow.query.filter_by(is_deleted=False)
    query = _apply_scope(query, file_id, sheet_id, sheet_ids)

    if low_only:
        query = low_stock_filter(query)

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                InventoryRow.identifier.like(like),
                InventoryRow.item_name.like(like),
                InventoryRow.manufacturer.like(like),
                InventoryRow.model.like(like),
                InventoryRow.capacity.like(like),
                InventoryRow.location.like(like),
                InventoryRow.status.like(like),
                cast(InventoryRow.data_json, Text).like(like),
            )
        )

    for col, value in filters.items():
        value = str(value or "").strip()
        if not value:
            continue
        query = query.filter(
            InventoryRow.data_json[str(col)].as_string().like(f"%{value}%")
        )

    total = query.count()
    total_pages = max((total + page_size - 1) // page_size, 1)
    page = min(page, total_pages)

    order_by_clause = InventoryRow.id.desc()

    if sort_col:
        normalized_fields = {
            "identifier": InventoryRow.identifier,
            "item_name": InventoryRow.item_name,
            "manufacturer": InventoryRow.manufacturer,
            "model": InventoryRow.model,
            "capacity": InventoryRow.capacity,
            "quantity": InventoryRow.quantity,
            "location": InventoryRow.location,
            "status": InventoryRow.status,
        }

        if sort_col in normalized_fields:
            column_expr = normalized_fields[sort_col]
        elif re.search(r"수량|재고|qty|quantity", sort_col, re.IGNORECASE):
            # 수량성 컴럼으로 보이는 동적(원본 엑셀) 컴럼은 문자열이 아니라 숫자로 정렬한다.
            column_expr = db.cast(
                InventoryRow.data_json[sort_col].as_string(), db.Numeric(18, 4)
            )
        else:
            column_expr = InventoryRow.data_json[sort_col].as_string()

        order_by_clause = column_expr.asc() if sort_dir == "asc" else column_expr.desc()

    rows = (
        query.order_by(order_by_clause)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return jsonify(
        {
            "items": [serialize_row(row) for row in rows],
            "count": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "columns": schema_columns(file_id, sheet_id, sheet_ids),
            "sort": sort_col,
            "dir": sort_dir,
        }
    )


@api_bp.get("/schema")
@login_required
def schema():
    logger.debug(
        "Schema request | file_id=%s | sheet_ids=%s",
        request.args.get("file_id"),
        request.args.get("sheet_ids"),
    )
    return jsonify(
        {
            "columns": schema_columns(
                request.args.get("file_id", type=int),
                request.args.get("sheet_id", type=int),
                _selected_sheet_ids(),
            )
        }
    )


@api_bp.get("/filters")
@login_required
def filters():
    logger.debug(
        "Filter metadata request | file_id=%s | sheet_ids=%s",
        request.args.get("file_id"),
        request.args.get("sheet_ids"),
    )
    sheet_id = request.args.get("sheet_id", type=int)
    file_id = request.args.get("file_id", type=int)
    sheet_ids = _selected_sheet_ids()

    columns_query = SheetColumn.query
    if sheet_ids:
        columns_query = columns_query.filter(SheetColumn.sheet_id.in_(sheet_ids))
    elif sheet_id:
        columns_query = columns_query.filter_by(sheet_id=sheet_id)
    elif file_id:
        columns_query = columns_query.join(
            ExcelSheet, SheetColumn.sheet_id == ExcelSheet.id
        ).filter(ExcelSheet.excel_file_id == file_id)

    columns = columns_query.order_by(SheetColumn.column_index, SheetColumn.id).all()

    out = []
    seen = set()

    # 컬럼마다 DISTINCT 한 번씩 — 예전처럼 5,000행 JSON 을 파이썬으로 훑지 않는다 (B-24).
    # 값 101개까지만 뽑아 30개 이하면 select, 그 이상이면 text 필터로 판단한다.
    for column in columns:
        name = column.original_name
        if not name or name in seen:
            continue
        seen.add(name)

        value_expr = InventoryRow.data_json[name].as_string()
        rows_query = db.session.query(value_expr).filter(InventoryRow.is_deleted == False)  # noqa: E712
        rows_query = _apply_scope(rows_query, file_id, sheet_id, sheet_ids)
        rows_query = (
            rows_query.filter(value_expr.isnot(None), value_expr != "")
            .distinct()
            .order_by(value_expr)
            .limit(101)
        )

        unique_values = [str(v) for (v,) in rows_query.all()][:100]
        filter_type = (
            "select" if len(unique_values) <= 30 else (column.filter_type or "text")
        )

        out.append(
            {
                "name": name,
                "type": filter_type,
                "data_type": column.data_type,
                "values": unique_values,
            }
        )

    return jsonify({"filters": out})


@api_bp.get("/files")
@login_required
def api_files():
    return jsonify(
        {
            "items": [
                {
                    "id": file.id,
                    "name": file.original_filename,
                    "status": file.processing_status,
                    "created_at": file.created_at.isoformat(),
                }
                for file in ExcelFile.query.order_by(ExcelFile.created_at.desc()).all()
            ]
        }
    )


@api_bp.get("/sheets/<int:file_id>")
@login_required
def api_sheets(file_id):
    return jsonify(
        {
            "items": [
                {
                    "id": sheet.id,
                    "name": sheet.sheet_name,
                    "type": sheet.sheet_type,
                    "rows": sheet.row_count,
                    "columns": sheet.column_count,
                }
                for sheet in (
                    ExcelSheet.query.filter_by(excel_file_id=file_id)
                    .order_by(ExcelSheet.sheet_order)
                    .all()
                )
            ]
        }
    )
