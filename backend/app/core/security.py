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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token ausente"
        )

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

    return f"human:{email}"
