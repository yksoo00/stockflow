import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(app):
    """Configure application, access, and error logs without exposing secrets."""
    log_dir = Path(os.getenv("LOG_DIR", str(Path(app.root_path).parent / "logs")))
    log_dir.mkdir(parents=True, exist_ok=True)

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    app_log = RotatingFileHandler(
        log_dir / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    app_log.setLevel(level)
    app_log.setFormatter(fmt)

    error_log = RotatingFileHandler(
        log_dir / "error.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_log.setLevel(logging.ERROR)
    error_log.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers when Flask's reloader initializes the app twice.
    for handler in list(root.handlers):
        if getattr(handler, "_stockflow_handler", False):
            root.removeHandler(handler)
    app_log._stockflow_handler = True
    error_log._stockflow_handler = True
    root.addHandler(app_log)
    root.addHandler(error_log)

    if os.getenv("LOG_CONSOLE", "1") == "1":
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(fmt)
        console._stockflow_handler = True
        root.addHandler(console)

    # Keep noisy third-party libraries from flooding application logs.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    app.logger.setLevel(level)
    app.logger.info(
        "StockFlow logging initialized | level=%s | dir=%s", level_name, log_dir
    )
