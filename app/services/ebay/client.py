import base64
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# 환경 설정
# ---------------------------------------------------------

EBAY_ENV = os.getenv("EBAY_ENV", "production").strip() or "production"
EBAY_MARKETPLACE = os.getenv("EBAY_MARKETPLACE", "EBAY_US").strip() or "EBAY_US"

# eBay는 독일/프랑스처럼 한국 전용 마켓플레이스가 따로 없다(EBAY_KR 존재하지 않음).
# 한국 구매자는 보통 ebay.com(EBAY_US)을 해외배송으로 이용하므로 EBAY_MARKETPLACE는 EBAY_US를 유지하고,
# 대신 배송비/배송가능 여부를 한국 구매자 기준으로 추정받기 위해 buyer country 컨텍스트만 따로 지정한다.
EBAY_BUYER_COUNTRY = os.getenv("EBAY_BUYER_COUNTRY", "KR").strip() or "KR"

# eBay Browse API가 한 번의 요청으로 내려줄 수 있는 최대 건수(공식 상한).
# 정렬 정확도를 위해 페이지네이션과 무관하게 항상 이만큼 통째로 받아온다.
POOL_LIMIT = 200

_OAUTH_URL = {
    "production": "https://api.ebay.com/identity/v1/oauth2/token",
    "sandbox": "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
}

_SEARCH_URL = {
    "production": "https://api.ebay.com/buy/browse/v1/item_summary/search",
    "sandbox": "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search",
}


# ---------------------------------------------------------
# OAuth 토큰 캐시
#
# eBay Browse API는 App(client credentials) 토큰이 필요하다.
# 매 요청마다 새로 발급받지 않고 만료 전까지 재사용한다.
# ---------------------------------------------------------

_token_cache = {"value": None, "expires_at": 0}


def _get_access_token():
    now = time.time()

    if _token_cache["value"] and _token_cache["expires_at"] > now + 30:
        return _token_cache["value"]

    app_id = os.getenv("EBAY_APP_ID", "").strip()
    cert_id = os.getenv("EBAY_CERT_ID", "").strip()

    if not app_id or not cert_id:
        return None

    credentials = base64.b64encode(f"{app_id}:{cert_id}".encode()).decode()

    try:
        resp = requests.post(
            _OAUTH_URL[EBAY_ENV],
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {credentials}",
            },
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            timeout=10,
        )
    except requests.RequestException:
        logger.exception("eBay OAuth token connection failed | env=%s", EBAY_ENV)
        return None

    if resp.status_code != 200:
        # 여기서 응답 본문을 그대로 남겨야 invalid_client / invalid_scope 등
        # eBay가 말하는 정확한 실패 사유를 확인할 수 있다.
        logger.error(
            "eBay OAuth token request failed | env=%s | status=%s | body=%s",
            EBAY_ENV,
            resp.status_code,
            resp.text[:500],
        )
        return None

    payload = resp.json()

    _token_cache["value"] = payload.get("access_token")
    _token_cache["expires_at"] = now + int(payload.get("expires_in", 7200))

    logger.info(
        "eBay OAuth token issued | env=%s | expires_in=%s",
        EBAY_ENV,
        payload.get("expires_in"),
    )

    return _token_cache["value"]


# ---------------------------------------------------------
# 정식 API 검색 (Browse API)
#
# eBay의 sort=price는 "상품가격"만 기준으로 정렬하며 배송비는 반영하지 않는다.
# 그래서 한 번에 넉넉히(POOL_LIMIT=200) 받아온 뒤, 우리가 직접 "가격+배송비" 총액
# 기준으로 전체를 재정렬한다. 페이지 단위로 나눠 받아서 그 페이지 안에서만 재정렬하면
# 총액은 더 싸지만 상품가격이 조금 높은 상품이 다음 페이지에 묻혀 안 보일 수 있기 때문이다.
# ---------------------------------------------------------


def _search_via_api(code):
    token = _get_access_token()

    if not token:
        return None

    try:
        resp = requests.get(
            _SEARCH_URL[EBAY_ENV],
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE,
                "X-EBAY-C-ENDUSERCTX": f"contextualLocation=country={EBAY_BUYER_COUNTRY}",
            },
            params={
                "q": code,
                "sort": "price",
                "limit": POOL_LIMIT,
            },
            timeout=15,
        )
    except requests.RequestException:
        logger.exception("eBay API search request failed | code=%s", code)
        return None

    if resp.status_code != 200:
        logger.warning(
            "eBay API search failed | code=%s | status=%s | body=%s",
            code,
            resp.status_code,
            resp.text[:300],
        )
        return None

    data = resp.json()
    items = []

    for item in data.get("itemSummaries", []):
        price = item.get("price") or {}
        shipping_list = item.get("shippingOptions") or [{}]
        shipping = shipping_list[0].get("shippingCost") or {}

        price_value = price.get("value")
        shipping_value = shipping.get("value")

        items.append(
            {
                "title": item.get("title"),
                "price": float(price_value) if price_value else None,
                "currency": price.get("currency"),
                "shipping": float(shipping_value) if shipping_value else 0.0,
                "condition": item.get("condition"),
                "url": item.get("itemWebUrl"),
                "image": (item.get("image") or {}).get("imageUrl"),
                "seller": (item.get("seller") or {}).get("username"),
                "location": (item.get("itemLocation") or {}).get("country"),
            }
        )

    # eBay가 보고하는 실제 전체 매칭 건수 (POOL_LIMIT보다 클 수 있음)
    ebay_total = data.get("total")

    logger.info(
        "eBay API search completed | code=%s | pool_size=%s | ebay_total=%s",
        code,
        len(items),
        ebay_total,
    )

    return items, ebay_total


def _sort_by_total_price(items):
    return sorted(
        items,
        key=lambda x: (x["price"] if x["price"] is not None else float("inf"))
        + (x.get("shipping") or 0),
    )


# ---------------------------------------------------------
# 공개 진입점
# ---------------------------------------------------------


def search_by_code(code, page=1, page_size=30):
    """
    code(품번/식별자)로 eBay 매물을 검색한다.

    내부적으로 항상 POOL_LIMIT(=200)건을 한 번에 받아 "가격+배송비" 총액 기준으로
    전체를 정렬한 뒤, page/page_size로 그 정렬된 결과를 잘라서 반환한다.
    (이렇게 해야 다음 페이지를 넘겨도 진짜 최저가 순서가 절대 깨지지 않는다.)

    반환값: (items, source, warning, page_total, ebay_total)
        items: 요청한 page 분량만 (page_size건 이하)
        source: 항상 "api" (예전의 공개 페이지 스크래핑 폴백은 eBay 봇 차단(403)과
                이용약관 문제로 제거했다 — B-14)
        warning: 사용자에게 알려줘야 할 주의사항, 없으면 None
        page_total: 우리가 확보해서 정렬한 전체 건수 (최대 POOL_LIMIT)
        ebay_total: eBay가 보고하는 실제 전체 매칭 건수. POOL_LIMIT보다 클 수 있다

    예외: 키가 없거나 인증/호출에 실패하면 RuntimeError 로 사용자용 사유를 올린다.
    """

    app_id = os.getenv("EBAY_APP_ID", "").strip()
    cert_id = os.getenv("EBAY_CERT_ID", "").strip()

    if not (app_id and cert_id):
        raise RuntimeError(
            "eBay 가격 조회가 설정되지 않았습니다. .env 에 EBAY_APP_ID / EBAY_CERT_ID 를 넣어주세요."
        )

    api_result = _search_via_api(code)

    if api_result is None:
        raise RuntimeError(
            "eBay API 호출에 실패했습니다. EBAY_APP_ID/EBAY_CERT_ID 와 EBAY_ENV(production/sandbox) "
            "조합을 확인하세요. 자세한 사유는 서버 로그(error.log)에 있습니다."
        )

    pool, ebay_total = api_result
    source = "api"
    warning = None

    pool_sorted = _sort_by_total_price(pool)
    page_total = len(pool_sorted)

    start = (page - 1) * page_size
    items = pool_sorted[start : start + page_size]

    logger.info(
        "eBay search page sliced | code=%s | source=%s | page=%s | page_size=%s | page_total=%s | ebay_total=%s",
        code,
        source,
        page,
        page_size,
        page_total,
        ebay_total,
    )

    return items, source, warning, page_total, ebay_total
