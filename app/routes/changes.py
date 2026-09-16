import logging

from flask import Blueprint, jsonify
from flask_login import login_required

from ..models import InventoryChange

changes_bp = Blueprint("changes", __name__)
logger = logging.getLogger(__name__)


@changes_bp.get("/changes")
@login_required
def changes():

    logger.debug("Change history requested")
    items = (
        InventoryChange.query.order_by(InventoryChange.created_at.desc())
        .limit(200)
        .all()
    )

    return jsonify(
        {
            "items": [
                {
                    "id": x.id,
                    "row_id": x.inventory_row_id,
                    "field": x.field_name,
                    "old": x.old_value,
                    "new": x.new_value,
                    "reason": x.reason,
                    "source": x.source,
                    "created_at": x.created_at.isoformat(),
                }
                for x in items
            ]
        }
    )
