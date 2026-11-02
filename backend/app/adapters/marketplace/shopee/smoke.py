"""Teste de fumaça da Shopee REAL, somente leitura.

    SHOPEE_APP_ID=... SHOPEE_SECRET=... python -m app.adapters.marketplace.shopee.smoke
    ... smoke --short-link     # além do resto, gera UM link curto (cria um link na sua conta)

Confere, com as suas credenciais, o que a documentação não garante: se a assinatura é aceita,
se os campos que pedimos existem, o que cada query devolve e o que fica faltando. Não grava
nada no banco do MP e não imprime credencial.
"""

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta

from app.adapters.marketplace.shopee.adapter import ShopeeAdapter
from app.adapters.marketplace.shopee.auth import ShopeeAuth
from app.adapters.marketplace.shopee.client import ShopeeClient, ShopeeError
from app.core.config import Settings

OK, FAIL = "ok ", "ERRO"


def run(adapter: ShopeeAdapter, *, short_link: bool, out=print) -> int:
    failures = 0

    def step(name: str, action):
        nonlocal failures
        try:
            detail = action()
            out(f"  {OK} {name}: {detail}")
        except ShopeeError as exc:
            failures += 1
            out(f"  {FAIL} {name}: [{exc.code}] {exc}")
        except Exception as exc:  # noqa: BLE001 - é um diagnóstico: mostra e segue
            failures += 1
            out(f"  {FAIL} {name}: {type(exc).__name__}: {exc}")

    state: dict = {}

    def products():
        offers = adapter.search_products(limit=5)
        state["offers"] = offers
        if not offers:
            return "a API respondeu, mas sem produtos"
        first = offers[0]
        filled = {k: v for k, v in first.data_available().items()}
        out(f"       exemplo: {first.title[:50]!r} | preço {first.price} | "
            f"comissão {first.commission_rate} | vendas {first.sales_volume} | nota {first.rating}")
        out(f"       campos preenchidos: {filled}")
        return f"{len(offers)} produtos"

    def conversions():
        today = datetime.now(UTC).date()
        records = adapter.fetch_conversions(since=today - timedelta(days=7), until=today)
        no_sub = sum(1 for r in records if r.sub_id is None)
        return f"{len(records)} conversões nos últimos 7 dias ({no_sub} sem sub_id)"

    def validated():
        today = datetime.now(UTC).date()
        records = adapter.fetch_validated_conversions(since=today - timedelta(days=60), until=today)
        return f"{len(records)} conversões liquidadas nos últimos 60 dias"

    out("Shopee — teste de fumaça (somente leitura)")
    step("productOfferV2 (assinatura + campos)", products)
    step("conversionReport (scroll)", conversions)
    step("validatedReport (scroll)", validated)

    if short_link:
        def link():
            offers = state.get("offers") or []
            if not offers:
                raise ShopeeError("sem produto para encurtar")
            stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
            created = adapter.generate_affiliate_link(
                origin_url=offers[0].product_url, sub_ids=(f"mp-smoke-{stamp}",)
            )
            return created.short_url

        step("generateShortLink (cria 1 link)", link)

    out("PASSOU" if failures == 0 else f"{failures} etapa(s) falharam")
    return 0 if failures == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--short-link", action="store_true")
    args = parser.parse_args()

    app_id, secret = os.environ.get("SHOPEE_APP_ID", ""), os.environ.get("SHOPEE_SECRET", "")
    if not (app_id and secret):
        sys.exit("Defina SHOPEE_APP_ID e SHOPEE_SECRET no ambiente.")

    settings = Settings(_env_file=None, mock_marketplace=False, shopee_app_id=app_id,
                        shopee_secret=secret,
                        shopee_api_url=os.environ.get("SHOPEE_API_URL", Settings().shopee_api_url))
    client = ShopeeClient(
        url=settings.shopee_api_url,
        auth=ShopeeAuth(app_id, secret),
        timeout=settings.shopee_timeout_seconds,
        min_interval=settings.shopee_min_interval_seconds,
        max_retries=settings.shopee_max_retries,
    )
    sys.exit(run(ShopeeAdapter(client), short_link=args.short_link))


if __name__ == "__main__":
    main()
