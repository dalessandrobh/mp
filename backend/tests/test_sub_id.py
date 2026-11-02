import re
from datetime import date

import pytest

from app.domain import sub_id
from app.domain.sub_id import InvalidSubId

DAY = date(2026, 9, 6)


def _build(**overrides) -> str:
    base = dict(
        marketplace_prefix="shp",
        product_id=18377,
        channel="meta",
        day=DAY,
        campaign_id=421,
        creative_id=7,
        max_length=64,
    )
    return sub_id.build(**{**base, **overrides})


def test_is_alphanumeric_only_because_shopee_rejects_separators():
    value = _build()

    assert value == "shpc00bpp000e6hcr0720260906meta"
    # Medido na API real: hífen e underline dão "invalid sub id"; letras e dígitos passam.
    assert re.fullmatch(r"[A-Za-z0-9]+", value)
    assert len(value) == 31  # exatamente o tamanho que a Shopee aceitou


def test_the_longest_realistic_value_stays_under_the_verified_limit():
    value = _build(product_id=36**6 - 1, campaign_id=36**4 - 1, creative_id=36**2 - 1,
                   channel="instagram")

    assert len(value) <= 48  # 48 foi aceito pela Shopee; 56 foi recusado


def test_round_trip_recovers_every_id():
    parts = sub_id.parse(_build())

    assert parts.marketplace == "shp"
    assert parts.product_id == 18377
    assert parts.campaign_id == 421
    assert parts.creative_id == 7
    assert parts.channel == "meta"
    assert parts.day == DAY


def test_missing_campaign_and_creative_round_trip_as_none():
    parts = sub_id.parse(_build(campaign_id=None, creative_id=None))

    assert parts.campaign_id is None
    assert parts.creative_id is None
    assert parts.product_id == 18377


def test_exceeding_max_length_fails_instead_of_truncating():
    with pytest.raises(InvalidSubId) as exc:
        _build(max_length=20)

    assert "SUBID_MAX_LENGTH" in exc.value.message


@pytest.mark.parametrize("channel", ["meta-ads", "meta_ads", "Meta", ""])
def test_channel_must_be_lowercase_alphanumeric(channel):
    with pytest.raises(InvalidSubId):
        _build(channel=channel)


def test_marketplace_prefix_is_exactly_three_characters():
    for bad in ("sh", "shpe", "sh-"):
        with pytest.raises(InvalidSubId):
            _build(marketplace_prefix=bad)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "garbage",
        "shpc0001p000001cr012026090",  # data incompleta
        "shpc0001p000001cr0120261399meta",  # data impossível
        "shp-c0001-p000001-cr01-20260906-meta",  # o formato antigo, com hífens
    ],
)
def test_parse_rejects_malformed_values(bad):
    with pytest.raises(InvalidSubId):
        sub_id.parse(bad)
