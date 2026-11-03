"""Guarda contra divulgar réplica/mercado paralelo. Regra pura.

Isto existe porque a varredura de comissão alta trouxe a cauda de ticket alto, e é
exatamente ali que se concentram anúncios de produto de marca que podem não ser o que
dizem ser. A API da Shopee não dá nenhum sinal para separar: não informa vendedor
verificado, não informa histórico da loja, e a nota vem quase sempre 5,00 sem contagem de
avaliações (`rating_count` chega nulo).

**Barrar é a política decidida** (03/11/2026), não um estágio intermediário: o suspeito
não vai para fila de aprovação, não é publicado. A razão é a assimetria entre os dois
erros — publicar réplica no nome do operador é prejuízo que não se desfaz, e não publicar
é só receita adiada. Trocar isso por aprovação manual compraria essa receita adiada ao
preço de uma decisão humana por produto, todos os dias, e o único erro que o humano pode
cometer nessa fila é o caro.

A regra é intencionalmente grosseira: preço acima do teto E (categoria de marca OU marca
no título). Não tenta adivinhar autenticidade; só identifica onde o erro custa caro.
"""

import re
import unicodedata
from dataclasses import dataclass

# Marcas cujo nome em anúncio de ticket alto justifica cautela. Não é lista de marcas
# proibidas: é lista de onde a falsificação é lucrativa o bastante para existir.
BRAND_WORDS = frozenset(
    {
        "apple", "iphone", "ipad", "macbook", "airpods", "samsung", "galaxy", "xiaomi",
        "redmi", "poco", "motorola", "sony", "playstation", "nintendo", "xbox", "jbl",
        "bose", "dyson", "gopro", "canon", "nikon", "dell", "lenovo", "asus", "acer",
        "lg", "philips", "electrolux", "brastemp", "consul", "nike", "adidas", "oakley",
        "rayban", "ray-ban", "rolex", "garmin", "huawei", "realme", "oneplus", "intel",
        "amd", "nvidia", "geforce",
    }
)

DEFAULT_PRICE_CEILING = 800


@dataclass(frozen=True)
class RiskInput:
    title: str | None
    price: float | None
    category_id: str | None


@dataclass(frozen=True)
class RiskVerdict:
    blocked: bool
    reason_code: str
    why: str


def _normalize(text: str) -> str:
    """Minúsculas sem acento: 'Eletrodomésticos' e 'eletrodomesticos' são a mesma coisa."""
    stripped = unicodedata.normalize("NFKD", text)
    return "".join(c for c in stripped if not unicodedata.combining(c)).lower()


def brands_in(title: str | None) -> tuple[str, ...]:
    """Marcas citadas no título, casando palavra inteira.

    Palavra inteira importa: 'lg' casaria dentro de 'algodão' e 'amd' dentro de 'amendoim'
    numa busca por substring, e aí o guarda barraria toalha e doce.
    """
    if not title:
        return ()
    words = set(re.findall(r"[a-z0-9-]+", _normalize(title)))
    return tuple(sorted(words & BRAND_WORDS))


def assess(
    data: RiskInput,
    *,
    price_ceiling: float = DEFAULT_PRICE_CEILING,
    brand_categories: frozenset[str] = frozenset(),
) -> RiskVerdict:
    if data.price is None:
        # Sem preço não há como avaliar o risco, e o produto também não deveria ter
        # chegado até aqui. Dado ausente não libera: espera.
        return RiskVerdict(True, "RISK_UNKNOWN_PRICE", "sem preço para avaliar o risco")
    if data.price <= price_ceiling:
        return RiskVerdict(False, "OK", f"preço R$ {data.price:.2f} dentro do teto")

    found = brands_in(data.title)
    in_category = bool(data.category_id and data.category_id in brand_categories)
    if found:
        return RiskVerdict(
            True,
            "RISK_HIGH_TICKET_BRAND",
            f"R$ {data.price:.2f} acima do teto e marca no título: {', '.join(found)}",
        )
    if in_category:
        return RiskVerdict(
            True,
            "RISK_HIGH_TICKET_CATEGORY",
            f"R$ {data.price:.2f} acima do teto em categoria de marca ({data.category_id})",
        )
    return RiskVerdict(
        False, "OK", f"R$ {data.price:.2f} acima do teto, mas sem marca nem categoria de risco"
    )
