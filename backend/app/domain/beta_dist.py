"""Distribuição Beta: média, quantis. Função pura, sem dependência externa.

Por que isso existe em vez de `scipy`: o backend tem 10 dependências e nenhuma delas pesa
50 MB. O que se precisa daqui são a beta incompleta regularizada e sua inversa, e as duas
cabem em 50 linhas de numérica padrão (fração continuada de Lentz + bisseção).

Para que serve, em uma frase: com `Beta(α, β)` descrevendo a taxa de conversão de um
produto, a **média** é a estimativa, o **quantil 10%** é o que se usa para decidir manter
ou cortar (conservador) e o **quantil 90%** é o que se usa para escolher o que testar
(otimismo diante da incerteza). Ver docs/plano-10k.md §3.3.
"""

import math

_EPS = 1e-30
_MAX_ITER = 300


def _log_beta(a: float, b: float) -> float:
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _betacf(a: float, b: float, x: float) -> float:
    """Fração continuada da beta incompleta, pelo método modificado de Lentz."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _EPS:
        d = _EPS
    d = 1.0 / d
    h = d
    for m in range(1, _MAX_ITER + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _EPS:
            d = _EPS
        c = 1.0 + aa / c
        if abs(c) < _EPS:
            c = _EPS
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _EPS:
            d = _EPS
        c = 1.0 + aa / c
        if abs(c) < _EPS:
            c = _EPS
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h


def cdf(x: float, a: float, b: float) -> float:
    """I_x(a, b): P(X <= x) para X ~ Beta(a, b)."""
    if not (a > 0 and b > 0):
        raise ValueError("Beta exige a > 0 e b > 0")
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(a * math.log(x) + b * math.log1p(-x) - _log_beta(a, b))
    # A fração continuada converge rápido só em um dos lados; do outro usa-se a simetria
    # I_x(a,b) = 1 - I_{1-x}(b,a).
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def quantile(q: float, a: float, b: float) -> float:
    """Inversa de `cdf` por bisseção: 80 passos levam a precisão ~1e-24.

    Bisseção e não Newton de propósito: a CDF é monótona, então bisseção nunca diverge,
    e aqui previsibilidade vale mais que velocidade.
    """
    if not 0.0 <= q <= 1.0:
        raise ValueError("quantil fora de [0, 1]")
    if q == 0.0:
        return 0.0
    if q == 1.0:
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(80):
        mid = (low + high) / 2
        if cdf(mid, a, b) < q:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def mean(a: float, b: float) -> float:
    return a / (a + b)
