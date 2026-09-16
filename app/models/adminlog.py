from .. import db
from ..utils.time import utcnow


class AdminLog(db.Model):
    """
    관리자가 수행한 모든 작업(엑셀 업로드/삭제/수정, 컬럼 추가, 사용자 생성,
    입고요청 승인/물품도착 등)을 한 곳에 모아두는 통합 활동 로그.
    """

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        index=True
    )

    action = db.Column(
        db.String(60),
        index=True
    )

    target_type = db.Column(
        db.String(40)
    )

    target_id = db.Column(
        db.Integer
    )

    detail = db.Column(
        db.Text
    )

    created_at = db.Column(
        db.DateTime,
        default=utcnow,
        index=True
    )

    user = db.relationship("User")
