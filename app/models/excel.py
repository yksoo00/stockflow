from .. import db
from ..utils.time import utcnow


class ExcelFile(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    original_filename = db.Column(
        db.String(255),
        nullable=False
    )

    stored_filename = db.Column(
        db.String(255),
        nullable=False
    )

    file_path = db.Column(
        db.String(500),
        nullable=False
    )

    file_hash = db.Column(
        db.String(64),
        index=True
    )

    file_size = db.Column(
        db.BigInteger
    )

    uploaded_by = db.Column(
        db.Integer,
        db.ForeignKey("user.id")
    )

    processing_status = db.Column(
        db.String(30),
        default="queued"
    )

    error_message = db.Column(
        db.Text
    )

    created_at = db.Column(
        db.DateTime,
        default=utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=utcnow,
        onupdate=utcnow
    )

    sheets = db.relationship(
        "ExcelSheet",
        backref="excel_file",
        cascade="all, delete-orphan"
    )


class ExcelSheet(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    excel_file_id = db.Column(
        db.Integer,
        db.ForeignKey("excel_file.id"),
        nullable=False,
        index=True
    )

    sheet_name = db.Column(
        db.String(255),
        nullable=False
    )

    sheet_order = db.Column(
        db.Integer
    )

    sheet_type = db.Column(
        db.String(30),
        default="table"
    )

    row_count = db.Column(
        db.Integer,
        default=0
    )

    column_count = db.Column(
        db.Integer,
        default=0
    )

    created_at = db.Column(
        db.DateTime,
        default=utcnow
    )

    columns = db.relationship(
        "SheetColumn",
        backref="sheet",
        cascade="all, delete-orphan"
    )

    tables = db.relationship(
        "DetectedTable",
        backref="sheet",
        cascade="all, delete-orphan"
    )

    rows = db.relationship(
        "InventoryRow",
        backref="sheet",
        cascade="all, delete-orphan"
    )


class DetectedTable(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    sheet_id = db.Column(
        db.Integer,
        db.ForeignKey("excel_sheet.id"),
        nullable=False
    )

    title = db.Column(
        db.String(255)
    )

    header_row = db.Column(
        db.Integer
    )

    start_row = db.Column(
        db.Integer
    )

    end_row = db.Column(
        db.Integer
    )

    start_col = db.Column(
        db.Integer
    )

    end_col = db.Column(
        db.Integer
    )

    table_type = db.Column(
        db.String(30),
        default="inventory"
    )

    created_at = db.Column(
        db.DateTime,
        default=utcnow
    )


class SheetColumn(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    sheet_id = db.Column(
        db.Integer,
        db.ForeignKey("excel_sheet.id"),
        nullable=False,
        index=True
    )

    table_id = db.Column(
        db.Integer,
        db.ForeignKey("detected_table.id")
    )

    column_index = db.Column(
        db.Integer
    )

    original_name = db.Column(
        db.String(255)
    )

    normalized_name = db.Column(
        db.String(255)
    )

    data_type = db.Column(
        db.String(30),
        default="string"
    )

    is_searchable = db.Column(
        db.Boolean,
        default=True
    )

    is_filterable = db.Column(
        db.Boolean,
        default=True
    )

    filter_type = db.Column(
        db.String(30),
        default="text"
    )
