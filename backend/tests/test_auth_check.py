"""O login do Supabase é compartilhado: só quem está em DASHBOARD_ALLOWED_EMAILS entra no MP."""

import jwt
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


def _token(email: str) -> dict:
    token = jwt.encode({"email": email}, get_settings().jwt_secret, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_only_listed_emails_pass_the_check():
    settings = get_settings().model_copy(update={"dashboard_allowed_emails": "dono@example.com"})
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        client = TestClient(app)
        ok = client.get("/api/v1/auth/check", headers=_token("Dono@Example.com"))
        assert ok.status_code == 200
        assert ok.json() == {"user": "Dono@Example.com"}

        other = client.get("/api/v1/auth/check", headers=_token("outro@example.com"))
        assert other.status_code == 403
        assert client.get("/api/v1/auth/check").status_code == 401
    finally:
        app.dependency_overrides.clear()
