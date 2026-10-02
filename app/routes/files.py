import hashlib
import json
import logging
import os
import shutil
import uuid
import zipfile
from pathlib import Path

from flask import (
    Blueprint,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from openpyxl.utils.exceptions import InvalidFileException
from werkzeug.utils import secure_filename

from .. import db
from ..models import (
    ChatSession,
    DetectedTable,
    DiskUnit,
    ExcelFile,
    ExcelSheet,
    InventoryChange,
    InventoryGroup,
    InventoryRow,
    SheetColumn,
    StockIn,
    StockOut,
    StockRequest,
)
from ..services.excel.exporter import export_excel, export_excel_from_db
from ..services.excel.parser import file_sha256, parse_workbook
from ..services.inventory.normalize import infer_field, normalize_row, to_number
from .common import admin_required, log_action, sync_group_quantity

files_bp = Blueprint("files", __name__)
logger = logging.getLogger(__name__)


# =========================================================
# 업로드 파일 실제 위치 찾기
# =========================================================
def _resolve_upload_file(excel_file):
    """
    DB에 저장된 file_path가 과거 app/uploads를 가리키고 있더라도
    현재 프로젝트 루트 uploads/에서 실제 파일을 찾는다.
    """

    stored_filename = excel_file.stored_filename

    if not stored_filename:
        return None

    candidates = []

    # -----------------------------------------------------
    # 1. DB에 저장된 기존 경로
    # -----------------------------------------------------
    if excel_file.file_path:
        candidates.append(Path(excel_file.file_path))

    # -----------------------------------------------------
    # 2. 현재 프로젝트 루트/uploads
    #
    # files.py 위치:
    # StockFlow/app/routes/files.py
    #
    # parents[0] = routes
    # parents[1] = app
    # parents[2] = StockFlow
    # -----------------------------------------------------
    project_root = Path(__file__).resolve().parents[2]

    candidates.append(project_root / "uploads" / stored_filename)

    # -----------------------------------------------------
    # 3. 현재 작업 디렉터리/uploads
    # -----------------------------------------------------
    candidates.append(Path.cwd() / "uploads" / stored_filename)

    # -----------------------------------------------------
    # 4. 환경변수 UPLOAD_DIR
    # -----------------------------------------------------
    upload_dir = os.getenv("UPLOAD_DIR")

    if upload_dir:
        candidates.append(Path(upload_dir) / stored_filename)

    # -----------------------------------------------------
    # 중복 제거 후 실제 존재하는 파일 검색
    # -----------------------------------------------------
    checked = set()

    for candidate in candidates:
        try:
            candidate = candidate.resolve()
        except OSError:
            continue

        candidate_key = str(candidate).lower()

        if candidate_key in checked:
            continue

        checked.add(candidate_key)

        if candidate.is_file():
            return candidate

    return None


# =========================================================
# Excel 목록
# =========================================================
@files_bp.get("/files")
@login_required
def files():
    return render_template(
        "pages/files/list.html",
        files=ExcelFile.query.order_by(ExcelFile.created_at.desc()).all(),
    )


# =========================================================
# Excel 상세
# =========================================================
@files_bp.get("/files/<int:file_id>")
@login_required
def file_detail(file_id):
    f = db.get_or_404(ExcelFile, file_id)

    return render_template(
        "pages/files/detail.html",
        file=f,
    )


# =========================================================
# Excel Export
# =========================================================
@files_bp.get("/files/<int:file_id>/export")
@login_required
def export_file(file_id):

    f = db.get_or_404(ExcelFile, file_id)

    logger.info(
        "Excel export started | file_id=%s | filename=%s | user_id=%s",
        file_id,
        f.original_filename,
        current_user.id,
    )

    # -----------------------------------------------------
    # 실제 Excel 파일 위치 확인
    # -----------------------------------------------------
    source_path = _resolve_upload_file(f)

    if source_path:
        logger.info(
            "Excel export source resolved | file_id=%s | path=%s",
            file_id,
            source_path,
        )

        # -------------------------------------------------
        # DB에 오래된 경로가 들어있다면 현재 실제 경로로 보정
        # -------------------------------------------------
        try:
            current_db_path = Path(f.file_path).resolve() if f.file_path else None

            if current_db_path is None or current_db_path != source_path.resolve():
                f.file_path = str(source_path.resolve())

                db.session.commit()

                logger.info(
                    "Excel file_path repaired | file_id=%s | path=%s",
                    file_id,
                    source_path,
                )

        except Exception:
            db.session.rollback()

            logger.exception(
                "Excel file_path repair failed | file_id=%s",
                file_id,
            )

    else:
        logger.warning(
            "Excel export source missing | file_id=%s | stored_filename=%s | db_path=%s",
            file_id,
            f.stored_filename,
            f.file_path,
        )

    # -----------------------------------------------------
    # Export 실행
    # -----------------------------------------------------
    # 원본이 없으면(업로드 폴더 유실, 다른 서버/볼륨의 DB 를 쓰는 경우 등) 404 대신
    # DB 값만으로 서식 없는 Excel 을 만들어 데이터라도 받을 수 있게 한다.
    from_original = source_path is not None

    try:
        if from_original:
            output = export_excel(f, source=source_path)
        else:
            output = export_excel_from_db(f)

    except Exception:
        db.session.rollback()

        logger.exception(
            "Excel export failed | file_id=%s | filename=%s",
            file_id,
            f.original_filename,
        )

        return jsonify(
            {
                "error": "Excel 내보내기에 실패했습니다.",
                "request_id": getattr(g, "request_id", "-"),
            }
        ), 500

    # -----------------------------------------------------
    # 다운로드 파일명
    # -----------------------------------------------------
    suffix = Path(f.original_filename).suffix.lower()

    extension = suffix if suffix in {".xlsx", ".xlsm"} else ".xlsx"

    stem = Path(f.original_filename).stem or "inventory"

    if from_original:
        download_name = f"{stem}_수정본{extension}"
    else:
        # 새로 만든 통합문서라 매크로가 없으므로 항상 xlsx
        extension = ".xlsx"
        download_name = f"{stem}_수정본(원본서식없음){extension}"

    logger.info(
        "Excel export completed | file_id=%s | filename=%s",
        file_id,
        f.original_filename,
    )

    log_action(
        "excel_export",
        detail=f"{f.original_filename} 수정본 내보내기"
        + ("" if from_original else " (원본 파일 없음 — DB 값으로 생성)"),
        target_type="excel_file",
        target_id=f.id,
    )
    db.session.commit()

    return send_file(
        output,
        as_attachment=True,
        download_name=download_name,
        mimetype=(
            "application/vnd.ms-excel.sheet.macroEnabled.12"
            if extension == ".xlsm"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
    )




# =========================================================
# Excel 삭제
# =========================================================
@files_bp.post("/files/<int:file_id>/delete")
@admin_required
def delete_file(file_id):

    f = db.get_or_404(ExcelFile, file_id)

    logger.info(
        "Excel delete started | file_id=%s | filename=%s | user_id=%s",
        file_id,
        f.original_filename,
        current_user.id,
    )

    path = _resolve_upload_file(f)

    if not path:
        logger.warning(
            "Excel delete source missing | file_id=%s | stored_filename=%s | db_path=%s",
            file_id,
            f.stored_filename,
            f.file_path,
        )

    # -----------------------------------------------------
    # FK 의존관계 정리 (B-16)
    #
    # 이력 테이블(StockOut/StockIn/StockRequest/DiskUnit)은 품목 정보를 스냅샷으로
    # 갖고 있으므로 삭제하지 않고 inventory_row_id 만 끊는다.
    # InventoryChange/ChatSession 은 행/파일 없이는 의미가 없어 함께 지운다.
    # -----------------------------------------------------
    row_ids = [
        rid for (rid,) in db.session.query(InventoryRow.id).filter_by(excel_file_id=f.id).all()
    ]
    sheet_ids = [
        sid for (sid,) in db.session.query(ExcelSheet.id).filter_by(excel_file_id=f.id).all()
    ]
    table_ids = (
        [
            tid
            for (tid,) in db.session.query(DetectedTable.id)
            .filter(DetectedTable.sheet_id.in_(sheet_ids))
            .all()
        ]
        if sheet_ids
        else []
    )
    group_ids = {
        gid
        for (gid,) in db.session.query(InventoryRow.inventory_group_id)
        .filter(InventoryRow.excel_file_id == f.id, InventoryRow.inventory_group_id.isnot(None))
        .distinct()
        .all()
    }

    original_filename = f.original_filename

    try:
        if row_ids:
            for model in (StockOut, StockIn, StockRequest, DiskUnit):
                model.query.filter(model.inventory_row_id.in_(row_ids)).update(
                    {model.inventory_row_id: None}, synchronize_session=False
                )

            InventoryChange.query.filter(
                InventoryChange.inventory_row_id.in_(row_ids)
            ).delete(synchronize_session=False)

            InventoryRow.query.filter(InventoryRow.id.in_(row_ids)).delete(
                synchronize_session=False
            )

        ChatSession.query.filter(
            db.or_(
                ChatSession.excel_file_id == f.id,
                ChatSession.sheet_id.in_(sheet_ids) if sheet_ids else False,
            )
        ).delete(synchronize_session=False)

        if table_ids:
            SheetColumn.query.filter(SheetColumn.table_id.in_(table_ids)).update(
                {SheetColumn.table_id: None}, synchronize_session=False
            )
            DetectedTable.query.filter(DetectedTable.id.in_(table_ids)).delete(
                synchronize_session=False
            )

        # 남은 SheetColumn / Sheet 는 ExcelFile cascade 로 제거
        db.session.delete(f)
        db.session.flush()

        # 행이 하나도 안 남은 InventoryGroup 정리, 남은 그룹은 합계 재계산
        for gid in group_ids:
            group = db.session.get(InventoryGroup, gid)
            if group is None:
                continue
            if not group.rows:
                db.session.delete(group)
            else:
                sync_group_quantity(group)

        log_action(
            "excel_delete",
            detail=f"{original_filename} 삭제 ({len(row_ids)}행)",
            target_type="excel_file",
            target_id=file_id,
        )
        db.session.commit()

    except Exception:
        db.session.rollback()
        logger.exception("Excel delete DB transaction failed | file_id=%s", file_id)
        flash("Excel 삭제 중 오류가 발생했습니다. 관리자 로그를 확인하세요.", "error")
        return redirect(url_for("files.file_detail", file_id=file_id))

    # DB 삭제가 끝난 뒤 실제 파일 삭제. 실패해도 요청 전체를 실패로 만들지 않는다.
    try:
        if path and path.exists():
            path.unlink()
            logger.info("Excel source file deleted | file_id=%s | path=%s", file_id, path)
    except OSError:
        logger.exception(
            "Excel source file delete failed after DB deletion | file_id=%s | path=%s",
            file_id,
            path,
        )

    logger.info("Excel delete completed | file_id=%s | filename=%s", file_id, original_filename)

    flash(f"{original_filename} 삭제되었습니다.", "success")

    return redirect(url_for("files.files"))


# =========================================================
# Excel Upload
# =========================================================
def _upload_root():
    """
    업로드 폴더. UPLOAD_DIR 이 없으면 프로젝트 루트/uploads.

    StockFlow/
    ├─ run.py
    ├─ uploads/       ← 여기
    └─ app/routes/files.py  (parents[2] = 프로젝트 루트)
    """
    root = Path(os.getenv("UPLOAD_DIR") or (Path(__file__).resolve().parents[2] / "uploads"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _restore_missing_originals(digest, uploaded_path, safe_stem):
    """
    file_hash 가 같은 ExcelFile 중 원본 파일이 서버에 없는 것에 uploaded_path 의 사본을 붙인다.
    기록마다 따로 복사한다 (한 기록을 삭제할 때 원본을 지우므로 파일을 공유하면 안 된다).
    복구한 ExcelFile 목록을 돌려준다.
    """
    restored = []
    for ef in ExcelFile.query.filter_by(file_hash=digest).order_by(ExcelFile.id).all():
        if _resolve_upload_file(ef) is not None:
            continue

        suffix = Path(ef.original_filename or "").suffix.lower()
        if suffix not in {".xlsx", ".xlsm"}:
            suffix = uploaded_path.suffix.lower()
        target = uploaded_path.parent / f"{uuid.uuid4().hex}_{safe_stem}{suffix}"
        shutil.copyfile(uploaded_path, target)

        ef.stored_filename = target.name
        ef.file_path = str(target.resolve())
        log_action(
            "excel_restore",
            detail=f"{ef.original_filename} 원본 파일 복구 (같은 내용 재업로드)",
            target_type="excel_file",
            target_id=ef.id,
        )
        restored.append(ef)
        logger.info("Excel original restored | file_id=%s | path=%s", ef.id, target)

    if restored:
        db.session.commit()
    return restored


def _group_key(normalized, raw_data):
    """
    InventoryGroup.group_key (B-12): 정규화 필드를 이어붙인 뒤 SHA-256.
    정규화 필드가 하나도 없으면 원본 행 전체를 기준으로 한다.
    """
    key = "|".join(
        str(normalized.get(k) or "")
        for k in ("identifier", "item_name", "manufacturer", "model", "capacity")
    )
    if not key.strip("|"):
        key = json.dumps(raw_data, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _column_dtype(headers_samples):
    """샘플 값으로 number/string 과 필터 타입을 정한다."""
    samples = headers_samples
    numeric_count = sum(to_number(x) is not None for x in samples)
    dtype = (
        "number"
        if samples and numeric_count >= max(2, int(len(samples) * 0.7))
        else "string"
    )
    unique_count = len(set(map(str, samples)))
    filter_type = "range" if dtype == "number" else ("select" if unique_count <= 30 else "text")
    return dtype, filter_type


def _ingest_workbook(ef, parsed):
    """
    parse_workbook() 결과를 DB 에 넣는다. 반환값: 저장한 행 수.

    B-23: 행마다 flush 하지 않고, 그룹 조회도 파일 단위로 한 번에 처리한다.
    B-15: SheetColumn.column_index 에는 실제 Excel 열 번호(t["cols"])를 넣는다.
    """
    # 1) 시트/테이블/컬럼 먼저 만들고, 행은 그룹 키를 모아둔 뒤 마지막에 한꺼번에 넣는다.
    pending_rows = []  # (sheet, table, row_number, data, normalized, group_key)

    for si, s in enumerate(parsed):
        es = ExcelSheet(
            excel_file_id=ef.id,
            sheet_name=s["sheet_name"],
            sheet_order=si,
            sheet_type=s["sheet_type"],
            row_count=sum(len(t["rows"]) for t in s["tables"]),
            column_count=max([len(t["headers"]) for t in s["tables"]] or [0]),
        )
        db.session.add(es)
        db.session.flush()

        for t in s["tables"]:
            headers = t["headers"]
            # 파서가 준 실제 열 인덱스(0-based). 없으면 순번으로 대체.
            excel_cols = t.get("cols") or list(range(len(headers)))

            dt = DetectedTable(
                sheet_id=es.id,
                title=s["sheet_name"],
                header_row=s.get("header_row"),
                start_row=(t["rows"][0]["row_number"] if t["rows"] else None),
                end_row=(t["rows"][-1]["row_number"] if t["rows"] else None),
                start_col=(min(excel_cols) + 1) if excel_cols else 1,
                end_col=(max(excel_cols) + 1) if excel_cols else len(headers),
                table_type="inventory",
            )
            db.session.add(dt)
            db.session.flush()

            for h, col0 in zip(headers, excel_cols, strict=False):
                samples = [
                    r["data"].get(h) for r in t["rows"][:50] if r["data"].get(h) not in (None, "")
                ]
                dtype, filter_type = _column_dtype(samples)
                db.session.add(
                    SheetColumn(
                        sheet_id=es.id,
                        table_id=dt.id,
                        column_index=col0 + 1,  # 1-based 실제 Excel 열
                        original_name=h,
                        normalized_name=infer_field(h),
                        data_type=dtype,
                        filter_type=filter_type,
                    )
                )

            for r in t["rows"]:
                d = r["data"]
                n = normalize_row(d)
                pending_rows.append((es, dt, r["row_number"], d, n, _group_key(n, d)))

    if not pending_rows:
        return 0

    # 2) 그룹: 기존 것은 한 번에 조회, 없는 것은 한 번에 생성
    keys = list({k for *_, k in pending_rows})
    groups = {}
    for i in range(0, len(keys), 500):
        chunk = keys[i : i + 500]
        for group in InventoryGroup.query.filter(InventoryGroup.group_key.in_(chunk)).all():
            groups[group.group_key] = group

    for *_, n, key in pending_rows:
        if key not in groups:
            group = InventoryGroup(
                group_key=key,
                identifier=n.get("identifier"),
                item_name=n.get("item_name"),
                manufacturer=n.get("manufacturer"),
                model=n.get("model"),
                capacity=n.get("capacity"),
                quantity=0,
            )
            db.session.add(group)
            groups[key] = group
    db.session.flush()

    # 3) 행 저장 + 그룹 합계 누적
    touched_groups = set()
    for es, dt, row_number, d, n, key in pending_rows:
        group = groups[key]
        q = n.get("quantity")
        group.quantity = (group.quantity or 0) + (q or 0)
        touched_groups.add(group)

        db.session.add(
            InventoryRow(
                excel_file_id=ef.id,
                sheet_id=es.id,
                table_id=dt.id,
                row_number=row_number,
                data_json=d,
                identifier=n.get("identifier"),
                item_name=n.get("item_name"),
                manufacturer=n.get("manufacturer"),
                model=n.get("model"),
                capacity=n.get("capacity"),
                quantity=q,
                location=n.get("location"),
                status=n.get("status"),
                inventory_group_id=group.id,
            )
        )

    db.session.flush()
    return len(pending_rows)


@files_bp.route("/upload", methods=["GET", "POST"])
@admin_required
def upload():

    if request.method == "POST":
        file = request.files.get("file")
        allow_duplicate = request.form.get("allow_duplicate") == "1"

        logger.info(
            "Excel upload request received | user_id=%s | filename=%s",
            current_user.id,
            getattr(file, "filename", None),
        )

        if not file or not file.filename:
            flash("업로드할 Excel 파일을 선택하세요.", "error")
            return redirect(url_for("files.upload"))

        original_filename = file.filename or "upload.xlsx"
        extension = Path(original_filename).suffix.lower()

        if extension not in {".xlsx", ".xlsm"}:
            flash("xlsx/xlsm 파일만 업로드할 수 있습니다.", "error")
            return redirect(url_for("files.upload"))

        root = _upload_root()

        # 한글 파일명이나 특수문자로 secure_filename() 결과가 비어버리는 것을 방지
        safe_stem = secure_filename(Path(original_filename).stem) or "inventory"
        stored = f"{uuid.uuid4().hex}_{safe_stem}{extension}"
        path = root / stored

        file.save(path)

        logger.info(
            "Excel upload saved | user_id=%s | path=%s | size=%s",
            current_user.id,
            path,
            path.stat().st_size if path.exists() else 0,
        )

        # -------------------------------------------------
        # 중복 업로드 검사 (B-17): 같은 내용의 파일이 이미 있으면 막는다.
        # -------------------------------------------------
        digest = file_sha256(path)
        duplicate = ExcelFile.query.filter_by(file_hash=digest).first()

        # 같은 내용의 기존 기록인데 원본 파일이 이 서버에 없으면(로컬 실행 ↔ Docker 처럼
        # 같은 DB 를 쓰는 다른 서버에서 올렸던 경우) 방금 받은 파일로 원본을 되살린다.
        # 예전엔 중복으로 막고 받은 파일을 지워서, 원본을 다시 올려도 내보내기가 계속 실패했다.
        restored = _restore_missing_originals(digest, path, safe_stem)

        if restored and not allow_duplicate:
            try:
                path.unlink()
            except OSError:
                pass
            flash(
                f"원본 파일을 복구했습니다: {restored[0].original_filename}. "
                "이제 원본 서식을 유지한 수정본 내보내기가 됩니다.",
                "success",
            )
            return redirect(url_for("files.file_detail", file_id=restored[0].id))

        if duplicate and not allow_duplicate:
            try:
                path.unlink()
            except OSError:
                pass
            flash(
                f"같은 내용의 파일이 이미 업로드되어 있습니다: {duplicate.original_filename} "
                f"({duplicate.created_at:%Y-%m-%d}). 그래도 올리려면 '중복이어도 업로드' 를 체크하세요.",
                "error",
            )
            return redirect(url_for("files.upload", duplicate_of=duplicate.id))

        try:
            parsed = parse_workbook(path)

            ef = ExcelFile(
                original_filename=original_filename,
                stored_filename=stored,
                file_path=str(path.resolve()),
                file_hash=digest,
                file_size=path.stat().st_size,
                uploaded_by=current_user.id,
                processing_status="processing",
            )
            db.session.add(ef)
            db.session.flush()

            row_count = _ingest_workbook(ef, parsed)

            ef.processing_status = "completed"

            log_action(
                "excel_upload",
                detail=f"{original_filename} 업로드 ({row_count}행)"
                + (" — 중복 허용" if duplicate else ""),
                target_type="excel_file",
                target_id=ef.id,
            )
            db.session.commit()

            logger.info(
                "Excel upload completed | file_id=%s | filename=%s | rows=%s | user_id=%s",
                ef.id,
                original_filename,
                row_count,
                current_user.id,
            )

            flash(f"업로드 완료: {original_filename} / {row_count}개 행", "success")

            return redirect(url_for("files.file_detail", file_id=ef.id))

        except Exception as e:
            db.session.rollback()

            logger.exception(
                "Excel upload processing failed | filename=%s | user_id=%s",
                original_filename,
                current_user.id,
            )

            try:
                if path.exists():
                    path.unlink()
            except Exception:
                logger.exception(
                    "Failed to delete uploaded Excel after processing error | path=%s", path
                )

            # SQL 오류 등은 쿼리/경로가 그대로 들어있으므로 사용자에게 원문을 보여주지 않는다.
            if isinstance(e, (zipfile.BadZipFile, InvalidFileException, KeyError)):
                message = "올바른 xlsx/xlsm 파일이 아니거나 손상된 파일입니다."
            else:
                message = (
                    "Excel 분석 중 오류가 발생했습니다. "
                    f"(request_id={getattr(g, 'request_id', '-')})"
                )

            flash(f"Excel 분석 오류: {message}", "error")

            return redirect(url_for("files.upload"))

    duplicate_of = request.args.get("duplicate_of", type=int)
    return render_template("pages/files/upload.html", duplicate_of=duplicate_of)
