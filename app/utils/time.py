"""
시간 처리 규칙 (B-20).

- DB에는 항상 **naive UTC** 로 저장한다 (기존 데이터와 호환, MySQL DATETIME).
- 화면/API 문자열로 내보낼 때만 APP_TIMEZONE(기본 Asia/Seoul) 으로 변환한다.
- SQL 에서 날짜/월/연 단위로 묶을 때도 로컬 시간대 기준이 되도록 `local_ts()` 를 거친다.
"""

import logging
import os
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, literal_column

logger = logging.getLogger(__name__)

_TZ_NAME = os.getenv("APP_TIMEZONE", "Asia/Seoul")

try:
    LOCAL_TZ = ZoneInfo(_TZ_NAME)
except ZoneInfoNotFoundError:
    # Windows 에는 IANA tz 데이터가 없어 `tzdata` 패키지가 필요하다. 없으면 KST 고정 오프셋으로 대체.
    logger.warning("Time zone %s not found (pip install tzdata). Falling back to UTC+9.", _TZ_NAME)
    LOCAL_TZ = timezone(timedelta(hours=9), "KST")


def utcnow():
    """datetime.utcnow() 대체. naive UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


def to_local(dt):
    """naive UTC → aware 로컬. None 은 그대로."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(LOCAL_TZ)


def fmt(dt, pattern="%Y-%m-%d %H:%M"):
    """naive UTC 를 로컬 시간 문자열로. None 이면 None."""
    local = to_local(dt)
    return local.strftime(pattern) if local else None


def local_offset_hours(at=None):
    """현재(또는 주어진 시점) 로컬 시간대의 UTC 오프셋(시간). KST 는 항상 9."""
    at = at or datetime.now(UTC)
    offset = LOCAL_TZ.utcoffset(at) or timedelta(0)
    return int(offset.total_seconds() // 3600)


def local_ts(column, dialect_name):
    """
    UTC 저장 컬럼을 로컬 시간대로 옮긴 SQL 표현식.
    DATE()/EXTRACT() 로 묶을 때 자정 전후 9시간이 전날로 잡히는 문제를 막는다.
    DST 가 없는 시간대(한국)를 가정한 고정 오프셋 방식.
    """
    hours = local_offset_hours()
    if hours == 0:
        return column
    if dialect_name == "mysql":
        return func.timestampadd(literal_column("HOUR"), hours, column)
    if dialect_name == "sqlite":
        return func.datetime(column, f"{hours:+d} hours")
    # postgresql 등: interval 연산
    return column + literal_column(f"INTERVAL '{hours} hours'")


def local_date_range_utc(day):
    """로컬 날짜(date) 하루 → UTC naive (start, end) 구간. 날짜 필터용."""
    start_local = datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ)
    end_local = start_local + timedelta(days=1)
    return (
        start_local.astimezone(UTC).replace(tzinfo=None),
        end_local.astimezone(UTC).replace(tzinfo=None),
    )
