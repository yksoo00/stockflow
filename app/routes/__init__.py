from .adminlog import adminlog_bp
from .ai import ai_bp
from .auth import auth_bp
from .changes import changes_bp
from .ebay import ebay_bp
from .files import files_bp
from .inventory import api_bp
from .pages import main_bp
from .sheets import sheets_bp
from .stats import stats_bp
from .stockin import stockin_bp
from .stockout import stockout_bp
from .stockrequest import stockrequest_bp
from .units import units_bp
from .users import users_bp


def register_blueprints(app):
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(sheets_bp, url_prefix="/api")
    app.register_blueprint(ai_bp, url_prefix="/api/ai")
    app.register_blueprint(changes_bp, url_prefix="/api")
    app.register_blueprint(ebay_bp, url_prefix="/api/ebay")
    app.register_blueprint(stats_bp)
    app.register_blueprint(stockout_bp)
    app.register_blueprint(stockin_bp)
    app.register_blueprint(stockrequest_bp)
    app.register_blueprint(units_bp)
    app.register_blueprint(adminlog_bp)
