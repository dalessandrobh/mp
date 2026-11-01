"""Formato do sub_id: a chave que liga uma venda ao produto, campanha e criativo.

    {mp}-c{campanha}-p{produto}-cr{criativo}-{canal}-{yyyymmdd}
    ex.: shp-c0001-p00a4f2-cr01-meta-20260906

Ids internos em base36 minúsculo, com zeros à esquerda. O hífen separa os
segmentos, então nenhum segmento pode conter hífen — o canal é validado por
isso. Id 0 significa "ainda não existe" (ex.: link gerado antes da campanha);
ids reais começam em 1.

Funções puras. O tamanho máximo é parâmetro de quem chama (UNKNOWN-4): estourar
levanta erro, nunca trunca.
"""

import re
from dataclasses import dataclass
from datetime import date

from app.core.exceptions import DomainError

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
_CHANNEL = re.compile(r"^[a-z0-9]+$")
_PATTERN = re.compile(
    r"^(?P<mp>[a-z0-9]+)-c(?P<campaign>[0-9a-z]+)-p(?P<product>[0-9a-z]+)"
    r"-cr(?P<creative>[0-9a-z]+)-(?P<channel>[a-z0-9]+)-(?P<date>\d{8})$"
)


class InvalidSubId(DomainError):
    status_code = 422
    code = "INVALID_SUB_ID"


@dataclass(frozen=True)
class SubIdParts:
    marketplace: str
    campaign_id: int | None
    product_id: int
    creative_id: int | None
    channel: str
    day: date


def to_base36(value: int, width: int) -> str:
    if value < 0:
        raise InvalidSubId("id negativo não cabe no sub_id", details={"value": value})
    digits = ""
    while value:
        value, rem = divmod(value, 36)
        digits = _ALPHABET[rem] + digits
    return (digits or "0").rjust(width, "0")


def build(
    *,
    marketplace_prefix: str,
    product_id: int,
    channel: str,
    day: date,
    campaign_id: int | None = None,
    creative_id: int | None = None,
    max_length: int,
) -> str:
    if not _CHANNEL.match(marketplace_prefix) or not _CHANNEL.match(channel):
        raise InvalidSubId(
            "prefixo e canal aceitam só [a-z0-9] (hífen é o separador)",
            details={"marketplace_prefix": marketplace_prefix, "channel": channel},
        )
    value = (
        f"{marketplace_prefix}-c{to_base36(campaign_id or 0, 4)}-p{to_base36(product_id, 6)}"
        f"-cr{to_base36(creative_id or 0, 2)}-{channel}-{day:%Y%m%d}"
    )
    if len(value) > max_length:
        raise InvalidSubId(
            f"sub_id de {len(value)} caracteres excede SUBID_MAX_LENGTH={max_length}",
            details={"sub_id": value, "max_length": max_length},
        )
    return value


def parse(sub_id: str) -> SubIdParts:
    """Inverso de `build`. Usado na ingestão para achar o produto de uma venda."""
    match = _PATTERN.match(sub_id or "")
    if match is None:
        raise InvalidSubId("sub_id fora do formato esperado", details={"sub_id": sub_id})
    try:
        day = date(
            int(match["date"][:4]), int(match["date"][4:6]), int(match["date"][6:])
        )
    except ValueError as exc:
        raise InvalidSubId("data inválida no sub_id", details={"sub_id": sub_id}) from exc

    campaign = int(match["campaign"], 36)
    creative = int(match["creative"], 36)
    return SubIdParts(
        marketplace=match["mp"],
        campaign_id=campaign or None,
        product_id=int(match["product"], 36),
        creative_id=creative or None,
        channel=match["channel"],
        day=day,
    )
