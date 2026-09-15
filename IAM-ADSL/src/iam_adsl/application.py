"""Application factory boundary.

The compatibility module registers existing routes.  This boundary lets us
move routes into blueprints incrementally, while callers get a stable factory.
"""

from flask import Flask

from .config import HOST, PORT, WAIT_TIMEOUT_SECONDS


def create_app() -> Flask:
    app = Flask("iam_adsl", template_folder="templates")
    app.config.from_mapping(
        IAM_ADSL_HOST=HOST,
        IAM_ADSL_PORT=PORT,
        WIMTECH_WAIT_TIMEOUT=WAIT_TIMEOUT_SECONDS,
    )
    return app
