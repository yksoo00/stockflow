import logging
import re

logger = logging.getLogger(__name__)


ALIASES = {
    "identifier": [
        "code",
        "part no",
        "part number",
        "partno",
        "품번",
        "자산번호",
        "부품번호",
        "코드",
    ],

    "item_name": [
        "품명",
        "제품명",
        "장비명",
        "item",
        "name",
    ],

    "manufacturer": [
        "제조사",
        "manufacturer",
        "maker",
    ],

    "model": [
        "모델명",
        "모델",
        "model",
        "model name",
    ],

    "capacity": [
        "용량",
        "capacity",
        "size",
    ],

    "quantity": [
        "수량",
        "재고수량",
        "재 고 수량",
        "qty",
        "quantity",
        "총 수량",
        "총수량",

        # 기존 Excel 호환
        "재고",
    ],

    "location": [
        "위치",
        "보관위치",
        "location",
        "storage",
    ],

    "status": [
        "상태",
        "status",
    ],
}


def norm(value):
    return re.sub(
        r"[^0-9a-z가-힣]",
        "",
        str(value).lower()
    )


def infer_field(name):
    normalized = norm(name)

    for field, aliases in ALIASES.items():

        for alias in aliases:

            alias_normalized = norm(alias)

            if normalized == alias_normalized:
                return field

    return None


def to_number(value):
    if value is None:
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()

    if not text:
        return None

    text = text.replace(",", "")

    # 숫자만 추출
    match = re.search(
        r"-?\d+(?:\.\d+)?",
        text
    )

    if not match:
        return None

    try:
        return float(
            match.group()
        )
    except Exception:
        return None


def find_quantity_key(data):
    """
    normalize_row()가 수량으로 삼은 원본 컴럼명(예: '수량', '재고' 등)을 그대로 돌려준다.
    출고 처리할 때 data_json의 수량 값도 같이 줄여야 하는데, 어느 키인지 모르면 줄일 수 없기 때문.
    찾는 기준은 normalize_row()의 수량 판단 로직과 동일하다.
    """

    strong_quantity_headers = {
        norm("수량"),
        norm("재고수량"),
        norm("재 고 수량"),
        norm("qty"),
        norm("quantity"),
        norm("총 수량"),
        norm("총수량"),
    }

    weak_quantity_headers = {
        norm("재고"),
    }

    candidates = []

    for key, value in data.items():

        if value in (None, ""):
            continue

        key_normalized = norm(key)

        if key_normalized in strong_quantity_headers:
            candidates.append((0, key))
        elif key_normalized in weak_quantity_headers:
            candidates.append((1, key))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])

    return candidates[0][1]


def normalize_row(data):
    result = {}

    # -----------------------------------------------------
    # 일반 필드
    # -----------------------------------------------------

    for key, value in data.items():

        if value in (None, ""):
            continue

        field = infer_field(key)

        if not field:
            continue

        if field == "quantity":
            continue

        if field not in result:
            result[field] = value

    # -----------------------------------------------------
    # 수량
    #
    # '재고' 컬럼에 FC/SAS가 들어가는 기존 Excel을
    # 고려하여 반드시 숫자값만 수량으로 인정한다.
    # -----------------------------------------------------

    quantity_candidates = []

    strong_quantity_headers = {
        norm("수량"),
        norm("재고수량"),
        norm("재 고 수량"),
        norm("qty"),
        norm("quantity"),
        norm("총 수량"),
        norm("총수량"),
    }

    weak_quantity_headers = {
        norm("재고"),
    }

    for key, value in data.items():

        if value in (None, ""):
            continue

        key_normalized = norm(key)

        if (
            key_normalized not in strong_quantity_headers
            and key_normalized not in weak_quantity_headers
        ):
            continue

        number = to_number(value)

        if number is None:
            continue

        if key_normalized in strong_quantity_headers:
            priority = 0
        else:
            priority = 1

        quantity_candidates.append(
            (
                priority,
                number
            )
        )

    if quantity_candidates:

        quantity_candidates.sort(
            key=lambda x: x[0]
        )

        result["quantity"] = (
            quantity_candidates[0][1]
        )

    return result
