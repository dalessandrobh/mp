"""Quanto um produto combina com pin orgânico. Regra pura; menor nota = melhor.

Por que existe: o ranking por receita esperada (EV) favorece ticket e comissão altos, e é aí
que ficam celular, notebook e eletrônico de marca, que quase não rendem clique em pin. Nos
primeiros dados reais (12/11/2026), os quatro produtos que receberam clique humano eram de
cozinha, moda e esporte, todos baratos. A amostra é minúscula (4 cliques), então isto é um
PRIOR de curadoria, não um resultado medido: serve para escolher o que testar primeiro, e
deve ser revisto quando houver cliques e vendas suficientes.

A nota soma dois eixos, cada um de 0 a 2: categoria (0 preferida, 1 neutra, 2 desencorajada)
e preço (0 até R$ 100, 1 até R$ 200, 2 acima). Preço desconhecido conta como médio.
"""

import unicodedata
from decimal import Decimal


def _norm(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text)
    return "".join(c for c in stripped if not unicodedata.combining(c)).lower().strip()


# Assuntos que o público do Pinterest BR procura e salva: casa, moda, beleza, bebê, pet.
PREFERRED_CATEGORIES = frozenset(
    _norm(n)
    for n in (
        "Casa e Utilidades",
        "Roupas Femininas e Lingerie",
        "Beleza",
        "Acessórios de Moda",
        "Bolsas e Carteiras",
        "Calçados",
        "Moda Infantil",
        "Mãe e Bebê",
        "Pet Shop",
        "Hobbies e Colecionáveis",
        "Papelaria e Escritório",
    )
)

# Eletrônico e peça técnica: ticket alto, muita marca, pouca busca por inspiração.
DISCOURAGED_CATEGORIES = frozenset(
    _norm(n)
    for n in (
        "Celulares e Acessórios",
        "Computadores e Periféricos",
        "Câmeras e Segurança",
        "Games e Consoles",
        "Peças de Moto",
        "Ferramentas e Diversos",
    )
)

PRICE_LOW = Decimal("100")
PRICE_MID = Decimal("200")


def category_penalty(name: str | None) -> int:
    if not name:
        return 1
    key = _norm(name)
    if key in PREFERRED_CATEGORIES:
        return 0
    if key in DISCOURAGED_CATEGORIES:
        return 2
    return 1


def price_penalty(price: Decimal | float | None) -> int:
    if price is None:
        return 1
    value = Decimal(str(price))
    if value <= PRICE_LOW:
        return 0
    if value <= PRICE_MID:
        return 1
    return 2


def penalty(category_name: str | None, price: Decimal | float | None) -> int:
    """0 (melhor) a 4 (pior)."""
    return category_penalty(category_name) + price_penalty(price)
