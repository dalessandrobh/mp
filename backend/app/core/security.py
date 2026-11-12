import hmac

import jwt
from fastapi import Depends, Header, HTTPException, status

from app.core.config import Settings, get_settings


def require_api_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> str:
    """Autenticação dos workflows do n8n. Comparação em tempo constante."""
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.n8n_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="API key inválida ou ausente"
        )
    return "n8n"


def require_dashboard_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> str:
    """Valida o JWT do dashboard e devolve o ator no formato 'human:<email>'."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token ausente")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido"
        ) from exc

    email = claims.get("email") or claims.get("sub")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sem identidade")

    allowed = settings.allowed_emails
    if allowed and str(email).lower() not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário não autorizado")

    return f"human:{email}"


def require_reader(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> str:
    """Leitura aceita o n8n (API key) ou o dashboard (JWT)."""
    if x_api_key:
        return require_api_key(x_api_key, settings)
    return require_dashboard_user(authorization, settings)
