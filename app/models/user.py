from flask_login import UserMixin

from .. import db
from ..utils.time import utcnow


class User(UserMixin, db.Model):

    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(80), unique=True, nullable=False, index=True)

    password_hash = db.Column(db.String(255), nullable=False)

    role = db.Column(db.String(30), default="user")

    name = db.Column(db.String(80))

    position = db.Column(db.String(80))

    # 알림 수신용. 관리자는 입고요청/저재고 알림을, 요청자는 승인/도착 알림을 받는다.
    email = db.Column(db.String(255))

    # 담당 사이트 (여러 개). 쉼표/줄바꿈으로 구분해 저장하고 site_list 로 읽는다.
    # 출고/입고/요청/시리얼 목록의 기본 필터, 출고·요청 모달의 사이트 선택지로 쓰인다.
    site = db.Column(db.Text)

    # 비활성 계정은 로그인할 수 없다 (삭제 대신 사용 — 이력의 처리자 이름이 남아야 하므로).
    active = db.Column(db.Boolean, default=True, nullable=False)

    # 관리자가 비밀번호를 초기화하면 True 로 바뀌고, 다음 로그인 때 변경을 강제한다.
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=utcnow)

    @property
    def is_active(self):
        # Flask-Login 이 로그인 허용 여부를 판단할 때 본다.
        return bool(self.active)

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def display_name(self):
        return self.name or self.username

    @property
    def site_list(self):
        return parse_site_list(self.site)

    @site_list.setter
    def site_list(self, values):
        values = parse_site_list(values)
        self.site = ", ".join(values) if values else None


def parse_site_list(raw):
    """'서울IDC, 부산DC' / 줄바꿈 구분 문자열 / 리스트 → 중복 제거된 사이트 이름 리스트."""
    if not raw:
        return []
    if isinstance(raw, list | tuple):
        items = raw
    else:
        items = str(raw).replace(chr(10), ",").replace(";", ",").split(",")
    out = []
    for item in items:
        s = str(item).strip()
        if s and s not in out:
            out.append(s)
    return out
