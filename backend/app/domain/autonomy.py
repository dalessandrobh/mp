"""Níveis de autonomia (PLANNING §7.3). Uma tabela, um lugar.

Cada ação automática pertence a uma classe, e cada classe tem um nível mínimo.
Ativar campanha NÃO é uma classe: não existe nível em que a plataforma ative
anúncio, então não há o que consultar.

Aprovação humana não passa por aqui — quem aprova no dashboard assume a
decisão, e as travas de dado (maturidade, SETTLED, orçamento) continuam valendo
na execução de qualquer jeito.
"""

from enum import StrEnum


class ActionClass(StrEnum):
    PROMOTE_CANDIDATE = "PROMOTE_CANDIDATE"      # QUALIFICATION -> CANDIDATE
    PORTFOLIO_CHANGE = "PORTFOLIO_CHANGE"        # entrar, sair, graduar, substituir
    GENERATE_LINKS = "GENERATE_LINKS"
    CREATE_CAMPAIGN = "CREATE_CAMPAIGN"          # sempre PAUSED
    ADJUST_BUDGET = "ADJUST_BUDGET"


MIN_LEVEL: dict[ActionClass, int] = {
    ActionClass.PROMOTE_CANDIDATE: 2,
    ActionClass.PORTFOLIO_CHANGE: 3,
    ActionClass.GENERATE_LINKS: 3,
    ActionClass.CREATE_CAMPAIGN: 4,
    ActionClass.ADJUST_BUDGET: 5,
}


def permits(level: int, action: ActionClass) -> bool:
    return level >= MIN_LEVEL[action]


def refusal(level: int, action: ActionClass) -> str:
    return (
        f"AI_AUTONOMY_LEVEL={level}: {action.value} exige nível {MIN_LEVEL[action]}+"
    )
