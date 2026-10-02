from flask import Blueprint, jsonify, render_template
from flask_login import login_required

from ..models import ExcelFile, InventoryRow
from .common import low_stock_filter

main_bp = Blueprint("main", __name__)


@main_bp.route("/health")
def health():
    return jsonify({"ok": True, "service": "inventory"})


@main_bp.route("/")
@login_required
def dashboard():
    files = ExcelFile.query.order_by(ExcelFile.created_at.desc()).all()

    total = InventoryRow.query.filter_by(is_deleted=False).count()

    low = low_stock_filter(InventoryRow.query).count()

    return render_template(
        "pages/dashboard.html",
        files=files,
        total=total,
        low=low,
    )


@main_bp.route("/chat")
@login_required
def chat():
    return render_template("pages/chat/index.html")


@main_bp.route("/sites/<path:site>")
@login_required
def site_detail(site):
    return render_template("pages/sites/detail.html", site=site)


@main_bp.route("/units")
@login_required
def units_page():
    return render_template("pages/units/index.html")


@main_bp.route("/ebay/<code>")
@login_required
def ebay(code):
    return render_template("pages/ebay/results.html", code=code)
