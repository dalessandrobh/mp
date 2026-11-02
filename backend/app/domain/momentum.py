"""Momento de vendas a partir da série de snapshots. Função pura, sem banco.

O que a série mede, e isso é medição nossa, não documentação da Shopee: o campo `sales`
**não é acumulado**. Medido em produção em 02/11/2026, em 241 pares consecutivos de
snapshots do mesmo produto, 27 subiram e 20 **caíram** — variações de até 409 unidades em
horas. É janela móvel. Logo a derivada do valor da janela é a *aceleração* das vendas:
janela subindo significa produto entrando em tendência. É o sinal mais valioso que temos,
e quem só lê a API num instante não o tem.

Duas decisões que sustentam o número:

* **Theil–Sen, não mínimos quadrados.** A inclinação é a MEDIANA das inclinações par a
  par. Um reset de janela ou um ponto fora da curva move a mediana quase nada e arrastaria
  uma regressão por quadrados mínimos.
* **O tempo vem de `captured_at`, nunca de "um dia".** A descoberta não grava snapshot
  quando nada muda, então a série é irregular por construção.
"""

import statistics
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

# Com dois pontos existe uma inclinação só, e mediana de um elemento não é robusta a nada.
MIN_POINTS = 3
# Abaixo disso a inclinação diária é extrapolação de uma janela de horas.
MIN_SPAN_DAYS = 0.5
SECONDS_PER_DAY = 86400.0


@dataclass(frozen=True)
class MomentumResult:
    """`relative` é adimensional: inclinação por dia dividida pelo nível atual.

    É ele que se compara entre produtos — 50 vendas/dia a mais significa muito num
    produto de 200 e quase nada num de 20.000.
    """

    slope_per_day: Decimal
    relative: Decimal | None
    points: int
    span_days: Decimal


def compute(series: list[tuple[datetime, int | None]]) -> MomentumResult | None:
    """None quando não há série suficiente: ausência de medição não é momento zero."""
    points = sorted(
        ((t, v) for t, v in series if v is not None), key=lambda item: item[0]
    )
    if len(points) < MIN_POINTS:
        return None

    span = (points[-1][0] - points[0][0]).total_seconds() / SECONDS_PER_DAY
    if span < MIN_SPAN_DAYS:
        return None

    slopes: list[float] = []
    for i in range(len(points) - 1):
        t_i, v_i = points[i]
        for j in range(i + 1, len(points)):
            t_j, v_j = points[j]
            days = (t_j - t_i).total_seconds() / SECONDS_PER_DAY
            if days <= 0:
                continue  # mesmo instante: não há inclinação entre eles
            slopes.append((v_j - v_i) / days)
    if not slopes:
        return None

    slope = statistics.median(slopes)
    level = points[-1][1]
    relative = Decimal(str(slope / level)).quantize(Decimal("0.000001")) if level else None
    return MomentumResult(
        slope_per_day=Decimal(str(slope)).quantize(Decimal("0.0001")),
        relative=relative,
        points=len(points),
        span_days=Decimal(str(span)).quantize(Decimal("0.001")),
    )
