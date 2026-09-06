"""Fórmulas de performance. Funções puras, sem banco e sem HTTP.

Regra que atravessa o arquivo inteiro: **dado ausente devolve None, nunca 0**.
Um produto sem cliques não tem CTR igual a zero — ele não tem CTR. Tratar as
duas coisas como iguais faria o motor de decisão cortar produto por falta de
medição em vez de por mau desempenho.
"""

from decimal import Decimal, InvalidOperation

Number = Decimal | int | float | None

_MONEY = Decimal("0.01")
_RATE = Decimal("0.00001")


def _dec(value: Number) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _ratio(numerator: Number, denominator: Number, quantum: Decimal) -> Decimal | None:
    num, den = _dec(numerator), _dec(denominator)
    if num is None or den is None or den == 0:
        return None
    return (num / den).quantize(quantum)


def ctr(clicks: Number, impressions: Number) -> Decimal | None:
    """Cliques por impressão. None se não houve impressão medida."""
    return _ratio(clicks, impressions, _RATE)


def cpc(ad_spend: Number, clicks: Number) -> Decimal | None:
    """Custo por clique. None se não houve clique."""
    return _ratio(ad_spend, clicks, Decimal("0.0001"))


def cvr(conversions: Number, clicks: Number) -> Decimal | None:
    """Conversões por clique. None se não houve clique."""
    return _ratio(conversions, clicks, _RATE)


def epc(revenue: Number, clicks: Number) -> Decimal | None:
    """Receita por clique. None se não houve clique."""
    return _ratio(revenue, clicks, Decimal("0.0001"))


def roas(revenue: Number, ad_spend: Number) -> Decimal | None:
    """Receita sobre investimento. None se não houve investimento."""
    return _ratio(revenue, ad_spend, Decimal("0.0001"))


def profit(revenue: Number, ad_spend: Number) -> Decimal | None:
    """Lucro absoluto. Precisa dos dois lados para existir."""
    rev, spend = _dec(revenue), _dec(ad_spend)
    if rev is None or spend is None:
        return None
    return (rev - spend).quantize(_MONEY)


def roi(revenue: Number, ad_spend: Number) -> Decimal | None:
    """(receita - custo) / custo. None se não houve investimento.

    Diferente do ROAS: ROI = 0 significa empatar, ROAS = 1 significa empatar.
    """
    rev, spend = _dec(revenue), _dec(ad_spend)
    if rev is None or spend is None or spend == 0:
        return None
    return ((rev - spend) / spend).quantize(Decimal("0.0001"))


def commission_value(price: Number, commission_rate: Number) -> Decimal | None:
    """Comissão em dinheiro. `commission_rate` é fração (0.085 = 8,5%)."""
    p, rate = _dec(price), _dec(commission_rate)
    if p is None or rate is None:
        return None
    return (p * rate).quantize(_MONEY)


def is_sample_sufficient(
    clicks: Number,
    impressions: Number,
    *,
    min_clicks: int,
    min_impressions: int,
) -> bool:
    """Amostra madura o bastante para decidir?

    Ausência de medição nunca conta como amostra suficiente.
    """
    c, i = _dec(clicks), _dec(impressions)
    if c is None or i is None:
        return False
    return c >= min_clicks and i >= min_impressions
