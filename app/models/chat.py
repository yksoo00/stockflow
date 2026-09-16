from .. import db
from ..utils.time import utcnow


class ChatSession(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id")
    )

    title = db.Column(
        db.String(255)
    )

    excel_file_id = db.Column(
        db.Integer,
        db.ForeignKey("excel_file.id")
    )

    sheet_id = db.Column(
        db.Integer,
        db.ForeignKey("excel_sheet.id")
    )

    created_at = db.Column(
        db.DateTime,
        default=utcnow
    )

    messages = db.relationship(
        "ChatMessage",
        backref="session",
        cascade="all, delete-orphan"
    )


class ChatMessage(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    session_id = db.Column(
        db.Integer,
        db.ForeignKey("chat_session.id"),
        index=True
    )

    role = db.Column(
        db.String(20)
    )

    content = db.Column(
        db.Text
    )

    created_at = db.Column(
        db.DateTime,
        default=utcnow
    )
