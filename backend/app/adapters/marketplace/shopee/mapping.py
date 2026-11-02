"""Payload da Shopee -> modelo canônico.

Regra que atravessa o arquivo: campo ausente vira None, NUNCA um valor inventado. Nada de
estimar preço original a partir do desconto, nem avaliação a partir de vendas — o score
decide o que fazer com o que não veio.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from app.adapters.marketplace.base import ConversionRecord, ProductOffer

# O dia de uma venda é o dia no Brasil, o mesmo do ledger de orçamento e do dashboard.
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

PRODUCT_FIELDS = """
  itemId productName productLink offerLink imageUrl
  commissionRate sellerCommissionRate shopeeCommissionRate commission
  sales priceMin priceMax priceDiscountRate ratingStar
  productCatIds shopId shopName shopType periodStartTime periodEndTime
"""

ORDER_FIELDS = """
  orders {
    orderId orderStatus
    items { itemId actualAmount qty itemTotalCommission fraudStatus }
  }
"""

CONVERSION_FIELDS = f"""
  utmContent purchaseTime completeTime orderStatus fraudStatus
  totalCommission netCommission
  {ORDER_FIELDS}
"""

VALIDATED_FIELDS = f"""
  utmContent purchaseTime clickTime conversionId
  totalCommission netCommission sellerCommission
  {ORDER_FIELDS}
"""


def to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def to_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def local_date(epoch_seconds) -> date | None:
    seconds = to_int(epoch_seconds)
    if seconds is None:
        return None
    return datetime.fromtimestamp(seconds, LOCAL_TZ).date()


def offer_from_product(node: dict) -> ProductOffer | None:
    """None se faltar o mínimo para existir: id, nome e link."""
    item_id, name, link = node.get("itemId"), node.get("productName"), node.get("productLink")
    if item_id in (None, "") or not name or not link:
        return None

    rating = to_decimal(node.get("ratingStar"))
    if rating is not None and rating <= 0:
        rating = None  # 0 estrela não existe: é "sem avaliação", não nota zero

    categories = node.get("productCatIds") or []
    return ProductOffer(
        external_product_id=str(item_id),
        external_shop_id=str(node["shopId"]) if node.get("shopId") not in (None, "") else None,
        title=name,
        # IDs, não nomes: é o que a API entrega (L1 > L2 > L3).
        category_path=tuple(str(c) for c in categories) or None,
        product_url=link,
        image_url=node.get("imageUrl") or None,
        # Menor preço da faixa: não superestima a comissão por venda.
        price=to_decimal(node.get("priceMin")),
        commission_rate=to_decimal(node.get("commissionRate")),
        rating=rating,
        sales_volume=to_int(node.get("sales")),
        raw_payload=node,
    )


def _order_records(node: dict, *, validated: bool) -> list[ConversionRecord]:
    sub_id = (node.get("utmContent") or "").strip() or None
    day = local_date(node.get("purchaseTime")) or local_date(node.get("clickTime"))
    day = day or local_date(node.get("completeTime"))
    if day is None:
        return []  # sem data não dá para pôr a venda em nenhum dia

    node_fraud = node.get("fraudStatus")
    records: list[ConversionRecord] = []

    for order in node.get("orders") or []:
        items = order.get("items") or []
        clean = [i for i in items if i.get("fraudStatus") != "FRAUD"]
        all_fraud = bool(items) and not clean
        fraud = "FRAUD" if node_fraud == "FRAUD" or all_fraud else node_fraud

        commissions = [to_decimal(i.get("itemTotalCommission")) for i in clean]
        amounts = [to_decimal(i.get("actualAmount")) for i in clean]
        records.append(
            ConversionRecord(
                external_order_id=str(order.get("orderId")),
                sub_id=sub_id,
                conversion_date=day,
                commission_value=_sum(commissions),
                order_value=_sum(amounts),
                # ValidatedReport só traz o que liquidou: sem status explícito, é COMPLETED.
                status=order.get("orderStatus") or node.get("orderStatus")
                or ("COMPLETED" if validated else "UNKNOWN"),
                fraud_status=fraud,
                payload=node,
            )
        )

    if not records:
        # Sem pedidos detalhados: usa o total da conversão, com id estável.
        key = node.get("conversionId") or f"{sub_id}-{node.get('purchaseTime')}"
        records.append(
            ConversionRecord(
                external_order_id=str(key),
                sub_id=sub_id,
                conversion_date=day,
                commission_value=to_decimal(node.get("totalCommission")),
                order_value=None,
                status=node.get("orderStatus") or ("COMPLETED" if validated else "UNKNOWN"),
                fraud_status=node_fraud,
                payload=node,
            )
        )
    return records


def _sum(values: list[Decimal | None]) -> Decimal | None:
    present = [v for v in values if v is not None]
    return sum(present, Decimal(0)) if present else None


def records_from_conversion(node: dict) -> list[ConversionRecord]:
    return _order_records(node, validated=False)


def records_from_validated(node: dict) -> list[ConversionRecord]:
    return _order_records(node, validated=True)
