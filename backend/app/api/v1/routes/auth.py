"""Verificação de acesso ao painel.

O login é do Supabase, compartilhado com outros apps: uma conta válida lá não é, por si só,
uma conta autorizada aqui. O painel chama este endpoint logo depois do login e só mantém a
sessão se ele aceitar (a lista é DASHBOARD_ALLOWED_EMAILS).
"""

from fastapi import APIRouter, Depends

from app.core.security import require_dashboard_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/check")
def check(user: str = Depends(require_dashboard_user)) -> dict:
    return {"user": user.removeprefix("human:")}
