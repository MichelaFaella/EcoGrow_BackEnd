from __future__ import annotations
import os, time
from flask import Flask, jsonify
from sqlalchemy.exc import OperationalError

from models.base import Base, engine
import models.entities  # noqa: F401
from api import api_blueprint

def create_app() -> Flask:
    app = Flask(__name__)

    # Aspetta il DB con retry esponenziale (max ~30s)
    backoff = 0.5
    for attempt in range(10):
        try:
            with engine.begin() as conn:
                Base.metadata.create_all(bind=conn)
            break
        except OperationalError:
            time.sleep(backoff)
            backoff = min(backoff * 2, 5.0)
    else:
        # ultimo tentativo fuori dal loop (fa raise se ancora giù)
        with engine.begin() as conn:
            Base.metadata.create_all(bind=conn)

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    app.register_blueprint(api_blueprint, url_prefix="/api")
    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")), debug=True)
