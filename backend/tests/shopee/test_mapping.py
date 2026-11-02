from datetime import date
from decimal import Decimal

from app.adapters.marketplace.shopee import mapping


def _product(**overrides) -> dict:
    node = {
        "itemId": 17979995178,
        "productName": "Fone Bluetooth",
        "productLink": "https://shopee.com.br/produto-i.1.17979995178",
        "imageUrl": "https://img/x.jpg",
        "commissionRate": "0.0850",
        "priceMin": "49.90",
        "priceMax": "89.90",
        "sales": 1520,
        "ratingStar": "4.8",
        "productCatIds": [100001, 100012],
        "shopId": 84499012,
    }
    return {**node, **overrides}


def test_product_maps_to_the_canonical_offer():
    offer = mapping.offer_from_product(_product())

    assert offer.external_product_id == "17979995178"
    assert offer.external_shop_id == "84499012"
    assert offer.price == Decimal("49.90")  # o menor da faixa
    assert offer.commission_rate == Decimal("0.0850")
    assert offer.sales_volume == 1520
    assert offer.rating == Decimal("4.8")
    assert offer.category_path == ("100001", "100012")


def test_fields_the_api_never_sends_stay_none_not_invented():
    offer = mapping.offer_from_product(_product())

    assert offer.stock is None and offer.rating_count is None and offer.original_price is None
    assert offer.data_available()["stock"] is False


def test_zero_stars_means_no_rating_not_a_bad_rating():
    assert mapping.offer_from_product(_product(ratingStar="0")).rating is None
    assert mapping.offer_from_product(_product(ratingStar="")).rating is None


def test_missing_prices_stay_none():
    offer = mapping.offer_from_product(_product(priceMin=None, commissionRate=None, sales=None))

    assert offer.price is None and offer.commission_rate is None and offer.sales_volume is None


def test_product_without_id_name_or_link_is_dropped():
    for broken in ({"itemId": None}, {"productName": ""}, {"productLink": None}):
        assert mapping.offer_from_product(_product(**broken)) is None


def test_garbage_numbers_become_none():
    offer = mapping.offer_from_product(_product(priceMin="abc", sales="x"))

    assert offer.price is None and offer.sales_volume is None


# ---------- conversões ----------

# 2026-09-06 23:30 em Brasília (UTC-3) = 2026-09-07 02:30 UTC: o dia é o do Brasil.
LATE_EVENING_BR = 1788748200


def _conversion(**overrides) -> dict:
    node = {
        "utmContent": "shp-c00bp-p000e6h-cr07-meta-20260906",
        "purchaseTime": LATE_EVENING_BR,
        "orderStatus": "COMPLETED",
        "fraudStatus": "VERIFIED",
        "totalCommission": "12.00",
        "orders": [
            {
                "orderId": "ORD-1",
                "orderStatus": "COMPLETED",
                "items": [
                    {"itemId": 1, "actualAmount": "100.00", "itemTotalCommission": "7.00",
                     "fraudStatus": "VERIFIED"},
                    {"itemId": 2, "actualAmount": "50.00", "itemTotalCommission": "5.00",
                     "fraudStatus": "VERIFIED"},
                ],
            }
        ],
    }
    return {**node, **overrides}


def test_conversion_day_is_the_brazilian_day():
    record = mapping.records_from_conversion(_conversion())[0]

    assert record.conversion_date == date(2026, 9, 6)


def test_order_commission_and_value_are_summed_from_items():
    record = mapping.records_from_conversion(_conversion())[0]

    assert record.external_order_id == "ORD-1"
    assert record.commission_value == Decimal("12.00")
    assert record.order_value == Decimal("150.00")
    assert record.sub_id == "shp-c00bp-p000e6h-cr07-meta-20260906"


def test_one_record_per_order_in_the_same_conversion():
    node = _conversion()
    node["orders"].append({"orderId": "ORD-2", "orderStatus": "PENDING", "items": []})

    records = mapping.records_from_conversion(node)

    assert [r.external_order_id for r in records] == ["ORD-1", "ORD-2"]
    assert records[1].status == "PENDING" and records[1].commission_value is None


def test_fraudulent_items_do_not_count_toward_commission():
    node = _conversion()
    node["orders"][0]["items"][1]["fraudStatus"] = "FRAUD"

    record = mapping.records_from_conversion(node)[0]

    assert record.commission_value == Decimal("7.00")
    assert record.fraud_status == "VERIFIED"


def test_order_with_only_fraudulent_items_is_marked_fraud():
    node = _conversion()
    for item in node["orders"][0]["items"]:
        item["fraudStatus"] = "FRAUD"

    record = mapping.records_from_conversion(node)[0]

    assert record.fraud_status == "FRAUD" and record.commission_value is None


def test_conversion_level_fraud_taints_every_order():
    record = mapping.records_from_conversion(_conversion(fraudStatus="FRAUD"))[0]

    assert record.fraud_status == "FRAUD"


def test_missing_or_blank_sub_id_is_not_attributable():
    assert mapping.records_from_conversion(_conversion(utmContent=""))[0].sub_id is None
    assert mapping.records_from_conversion(_conversion(utmContent=None))[0].sub_id is None


def test_validated_report_without_status_is_completed():
    node = _conversion(orderStatus=None)
    node["orders"][0]["orderStatus"] = None

    assert mapping.records_from_validated(node)[0].status == "COMPLETED"
    assert mapping.records_from_conversion(node)[0].status == "UNKNOWN"


def test_conversion_without_orders_falls_back_to_the_total():
    node = _conversion(orders=[], conversionId=987)

    record = mapping.records_from_validated(node)[0]

    assert record.external_order_id == "987" and record.commission_value == Decimal("12.00")


def test_conversion_without_any_date_is_skipped():
    assert mapping.records_from_conversion(_conversion(purchaseTime=None)) == []
