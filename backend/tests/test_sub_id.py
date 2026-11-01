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


def test_uses_hyphen_as_separator():
    value = _build()

    assert value == "shp-c00bp-p000e6h-cr07-meta-20260906"
    assert value.count("-") == 5


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


def test_channel_with_hyphen_is_rejected():
    with pytest.raises(InvalidSubId):
        _build(channel="meta-ads")


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "garbage",
        "shp-c0001-p000001-cr01-meta-2026090",
        "shp-c0001-p000001-cr01-meta-20261399",
    ],
)
def test_parse_rejects_malformed_values(bad):
    with pytest.raises(InvalidSubId):
        sub_id.parse(bad)
