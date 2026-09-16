from .. import db
from ..utils.time import utcnow


class InventoryGroup(db.Model):
    """
    같은 품목(품번/품명/제조사/모델/용량이 같은 행)을 Excel 파일에 관계없이 묶는 집계 단위.
    quantity 는 소속 행들의 quantity 합계이며, 행 수량이 바뀔 때마다
    common.sync_group_quantity() 로 다시 계산한다.
    """

    id = db.Column(db.Integer, primary_key=True)

    # 정규화 필드를 이어붙인 문자열의 SHA-256. (원문을 넣으면 512자를 넘어 저장이 실패했다)
    group_key = db.Column(db.String(512), unique=True, index=True)

    identifier = db.Column(db.String(255), index=True)
    item_name = db.Column(db.String(255), index=True)
    manufacturer = db.Column(db.String(255), index=True)
    model = db.Column(db.String(255), index=True)
    capacity = db.Column(db.String(100), index=True)

    quantity = db.Column(db.Float, default=0)

    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class InventoryRow(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    excel_file_id = db.Column(
        db.Integer, db.ForeignKey("excel_file.id"), nullable=False, index=True
    )
    sheet_id = db.Column(
        db.Integer, db.ForeignKey("excel_sheet.id"), nullable=False, index=True
    )
    table_id = db.Column(db.Integer, db.ForeignKey("detected_table.id"))

    row_number = db.Column(db.Integer)

    data_json = db.Column(db.JSON, nullable=False)

    identifier = db.Column(db.String(255), index=True)
    item_name = db.Column(db.String(255), index=True)
    manufacturer = db.Column(db.String(255), index=True)
    model = db.Column(db.String(255), index=True)
    capacity = db.Column(db.String(100), index=True)
    quantity = db.Column(db.Float, index=True)
    location = db.Column(db.String(255), index=True)
    status = db.Column(db.String(100), index=True)

    inventory_group_id = db.Column(
        db.Integer, db.ForeignKey("inventory_group.id"), index=True
    )

    is_deleted = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    excel_file = db.relationship(
        "ExcelFile", backref=db.backref("rows", cascade="all, delete-orphan")
    )
    group = db.relationship("InventoryGroup", backref="rows")


class InventoryChange(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    inventory_row_id = db.Column(
        db.Integer, db.ForeignKey("inventory_row.id"), index=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))

    change_type = db.Column(db.String(40))
    field_name = db.Column(db.String(255))
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    reason = db.Column(db.Text)
    source = db.Column(db.String(30), default="web")

    created_at = db.Column(db.DateTime, default=utcnow)


class StockOut(db.Model):
    """
    출고(반출) 이력. 항목 상세보기에서 출고를 기록하면
    해당 InventoryRow.quantity가 줄어들고 여기에 한 줄 남는다.

    취소(cancelled_at 이 채워짐)된 출고는 수량이 원복되며, 통계/목록 기본 조회에서는 제외된다.
    """

    id = db.Column(db.Integer, primary_key=True)

    inventory_row_id = db.Column(
        db.Integer, db.ForeignKey("inventory_row.id"), nullable=True, index=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)

    # 출고 시점의 품목 정보를 그대로 복사해둔다.
    # (나중에 해당 InventoryRow/Excel이 삭제되어도 출고 이력은 그대로 남아있어야 하므로)
    identifier = db.Column(db.String(255), index=True)
    item_name = db.Column(db.String(255))

    site = db.Column(db.String(120), index=True)
    quantity = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(255))

    # 장애 티켓 번호 / 현장 담당자 (선택)
    ticket_no = db.Column(db.String(80), index=True)
    handler = db.Column(db.String(80))

    # 출고된 디스크 시리얼 (줄바꿈 구분). 개체 단위 추적은 DiskUnit 이 담당하고 여기는 스냅샷.
    serials = db.Column(db.Text)

    # 취소/반납
    cancelled_at = db.Column(db.DateTime, index=True)
    cancelled_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    cancel_reason = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=utcnow, index=True)

    row = db.relationship("InventoryRow", backref="stock_outs")
    user = db.relationship("User", foreign_keys=[user_id])
    cancelled_by = db.relationship("User", foreign_keys=[cancelled_by_id])

    @property
    def is_cancelled(self):
        return self.cancelled_at is not None


class StockRequest(db.Model):
    """
    입고 요청(자동/수동) + 승인/도착처리 이력.

    생성 경로:
      - source="auto": 출고 후 재고가 임계값 이하가 되면 stockout 라우트에서 자동 생성된다.
      - source="manual": 상세보기 모달에서 사용자가 직접 등록

    상태 흐름:
      requested -(관리자 승인)-> approved -(관리자 물품도착)-> arrived
      "arrived"가 되는 순간 실제 InventoryRow.quantity에 요청수량만큼 가산된다(=자동입고).
    """

    id = db.Column(db.Integer, primary_key=True)

    inventory_row_id = db.Column(
        db.Integer, db.ForeignKey("inventory_row.id"), nullable=True, index=True
    )

    identifier = db.Column(db.String(255), index=True)
    item_name = db.Column(db.String(255))
    site = db.Column(db.String(120), index=True)
    quantity = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(255))

    source = db.Column(db.String(20), default="manual", index=True)
    status = db.Column(db.String(20), default="requested", index=True)

    requested_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    approved_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    approved_at = db.Column(db.DateTime)
    arrived_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    arrived_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=utcnow, index=True)

    row = db.relationship("InventoryRow", backref="stock_requests")
    requested_by = db.relationship("User", foreign_keys=[requested_by_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])
    arrived_by = db.relationship("User", foreign_keys=[arrived_by_id])


class StockIn(db.Model):
    """
    입고(재고 가산) 이력. StockOut과 대칭.

    생성 경로:
      - source="manual": 상세보기 모달의 "입고" 버튼으로 즉시 DB 반영
      - source="auto_request": StockRequest가 "물품도착" 처리되면서 자동으로 생성
      - source="cancel_out": 출고 취소로 수량이 원복될 때 (stock_out 취소 이력과 짝)
    """

    id = db.Column(db.Integer, primary_key=True)

    inventory_row_id = db.Column(
        db.Integer, db.ForeignKey("inventory_row.id"), nullable=True, index=True
    )
    stock_request_id = db.Column(
        db.Integer, db.ForeignKey("stock_request.id"), nullable=True, index=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)

    identifier = db.Column(db.String(255), index=True)
    item_name = db.Column(db.String(255))
    site = db.Column(db.String(120), index=True)
    quantity = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(255))
    source = db.Column(db.String(20), default="manual", index=True)

    # 입고된 디스크 시리얼 (줄바꿈 구분)
    serials = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=utcnow, index=True)

    row = db.relationship("InventoryRow", backref="stock_ins")
    request = db.relationship("StockRequest", backref="stock_in")
    user = db.relationship("User")


class DiskUnit(db.Model):
    """
    디스크 개체(시리얼번호) 단위 추적.

    입고 때 시리얼을 적으면 in_stock 으로 생기고, 출고 때 시리얼을 적으면 out 으로 바뀌며
    어느 사이트로 나갔는지 남는다. 출고 취소 시 다시 in_stock 으로 돌아온다.
    """

    STATUS_IN_STOCK = "in_stock"
    STATUS_OUT = "out"

    id = db.Column(db.Integer, primary_key=True)

    serial = db.Column(db.String(120), unique=True, nullable=False, index=True)

    identifier = db.Column(db.String(255), index=True)
    item_name = db.Column(db.String(255))

    inventory_row_id = db.Column(
        db.Integer, db.ForeignKey("inventory_row.id"), nullable=True, index=True
    )

    status = db.Column(db.String(20), default=STATUS_IN_STOCK, nullable=False, index=True)
    site = db.Column(db.String(120), index=True)

    stock_in_id = db.Column(db.Integer, db.ForeignKey("stock_in.id"), nullable=True)
    stock_out_id = db.Column(db.Integer, db.ForeignKey("stock_out.id"), nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    row = db.relationship("InventoryRow", backref="disk_units")
    stock_in = db.relationship("StockIn", backref="disk_units")
    stock_out = db.relationship("StockOut", backref="disk_units")
