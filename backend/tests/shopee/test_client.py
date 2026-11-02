import httpx
import pytest

from app.adapters.marketplace.shopee.auth import ShopeeAuth
from app.adapters.marketplace.shopee.client import (
    ShopeeAuthError,
    ShopeeClient,
    ShopeeError,
    ShopeeInvalidParams,
    ShopeeRateLimited,
)
from tests.shopee.fakes import APP_ID, SECRET, FakeShopee, error


class Clock:
    """Relógio e sleep falsos: o tempo só anda quando o código dorme."""

    def __init__(self) -> None:
        self.now = 1_800_000_000.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _client(server: FakeShopee, clock: Clock, **kwargs) -> ShopeeClient:
    return ShopeeClient(
        url="https://shopee.test/graphql",
        auth=ShopeeAuth(APP_ID, SECRET),
        http=server.client(),
        clock=clock.time,
        sleep=clock.sleep,
        **{"min_interval": 0, **kwargs},
    )


def test_signature_matches_the_exact_body_that_was_sent():
    server = FakeShopee(ping=lambda v, n: {"ping": "ok"})

    data = _client(server, Clock()).execute("query ping { ping }", {"a": "ç ã é", "b": 1})

    assert data == {"ping": "ok"}  # o servidor falso recusa com 10020 se o hash divergir


def test_credentials_are_required():
    with pytest.raises(ValueError):
        ShopeeAuth("", "x")


def test_header_follows_the_documented_order():
    header = ShopeeAuth("1", "s").header("{}", 1577836800)

    assert header.startswith("SHA256 Credential=1, Signature=")
    assert header.endswith(", Timestamp=1577836800")


def test_rate_limit_is_retried_with_exponential_backoff():
    def handler(variables, n):
        return error(10030, "Rate limit exceeded") if n < 3 else {"ping": "ok"}

    clock = Clock()
    server = FakeShopee(ping=handler)

    assert _client(server, clock).execute("query ping { ping }") == {"ping": "ok"}
    assert len(server.calls) == 3
    first, second = clock.sleeps
    assert 0.7 <= first <= 1.3 and 1.4 <= second <= 2.6  # ~1s e ~2s, com jitter


def test_rate_limit_gives_up_after_the_retry_budget():
    server = FakeShopee(ping=lambda v, n: error(10030, "Rate limit exceeded"))

    with pytest.raises(ShopeeRateLimited):
        _client(server, Clock(), max_retries=2).execute("query ping { ping }")

    assert len(server.calls) == 3  # 1 + 2 retentativas


@pytest.mark.parametrize("code", [10020, 10031, 10033, 10035])
def test_auth_and_access_errors_fail_at_once_without_retry(code):
    server = FakeShopee(ping=lambda v, n: error(code, "nope"))

    with pytest.raises(ShopeeAuthError) as exc:
        _client(server, Clock()).execute("query ping { ping }")

    assert exc.value.code == code and len(server.calls) == 1


def test_invalid_params_is_its_own_error():
    server = FakeShopee(ping=lambda v, n: error(11001, "Params Error: scrollId"))

    with pytest.raises(ShopeeInvalidParams):
        _client(server, Clock()).execute("query ping { ping }")


def test_server_errors_are_retried_then_reported():
    server = FakeShopee(ping=lambda v, n: httpx.Response(503))

    with pytest.raises(ShopeeError, match="indisponível"):
        _client(server, Clock(), max_retries=1).execute("query ping { ping }")

    assert len(server.calls) == 2


def test_http_429_counts_as_rate_limit():
    server = FakeShopee(ping=lambda v, n: httpx.Response(429) if n == 1 else {"ping": "ok"})

    assert _client(server, Clock()).execute("query ping { ping }") == {"ping": "ok"}


def test_each_attempt_is_signed_with_a_fresh_timestamp():
    server = FakeShopee(ping=lambda v, n: error(10030, "x") if n < 3 else {"ping": "ok"})
    clock = Clock()

    _client(server, clock).execute("query ping { ping }")

    stamps = [
        int(r.headers["Authorization"].rsplit("Timestamp=", 1)[1]) for r in server.requests
    ]
    # Depois de ~1s + ~2s de espera o relógio andou: um timestamp reaproveitado expiraria.
    assert stamps[2] > stamps[0]


def test_minimum_interval_between_calls_is_enforced():
    server = FakeShopee(ping=lambda v, n: {"ping": "ok"})
    clock = Clock()
    client = _client(server, clock, min_interval=0.5)

    client.execute("query ping { ping }")
    client.execute("query ping { ping }")

    assert clock.sleeps and clock.sleeps[0] == pytest.approx(0.5)
