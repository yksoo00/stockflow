import logging

from flask import Blueprint, jsonify, request
from flask_login import login_required

from ..services.ebay.client import search_by_code

ebay_bp = Blueprint("ebay_api", __name__)
logger = logging.getLogger(__name__)


@ebay_bp.get("/search")
@login_required
def ebay_search():

    code = request.args.get("q", "").strip()

    if not code:
        return jsonify({"error": "검색할 code를 입력하세요."}), 400

    # 한 페이지에 넉넉히 100건까지 보여준다 (서비스 내부적으로는 최대 200건을 받아
    # 총액 기준으로 전체 정렬한 뒤 그 안에서 페이지를 나누므로, 페이지가 넘어가도
    # 최저가 순서가 깨지지 않는다).
    page_size = min(max(request.args.get("limit", 10, type=int), 1), 200)
    page = max(request.args.get("page", 1, type=int), 1)

    logger.info(
        "eBay price search requested | code=%s | page=%s | page_size=%s",
        code,
        page,
        page_size,
    )

    try:
        items, source, warning, page_total, ebay_total = search_by_code(
            code, page=page, page_size=page_size
        )

    except RuntimeError as exc:
        # search_by_code 가 사용자 안내용으로 직접 만든 메시지만 그대로 내보낸다.
        logger.warning("eBay price search unavailable | code=%s | reason=%s", code, exc)

        return jsonify({"error": str(exc)}), 502

    except Exception:
        logger.exception("eBay price search failed | code=%s", code)

        return jsonify({"error": "eBay 조회 중 오류가 발생했습니다. 잠시 후 다시 시도하세요."}), 502

    total_pages = max((page_total + page_size - 1) // page_size, 1)
    has_next = page < total_pages

    logger.info(
        "eBay price search completed | code=%s | source=%s | page=%s | count=%s | page_total=%s | ebay_total=%s",
        code,
        source,
        page,
        len(items),
        page_total,
        ebay_total,
    )

    return jsonify(
        {
            "query": code,
            "source": source,
            "warning": warning,
            "count": len(items),
            "items": items,
            "page": page,
            "limit": page_size,
            "total": ebay_total,
            "pool_total": page_total,
            "total_pages": total_pages,
            "has_next": has_next,
        }
    )
