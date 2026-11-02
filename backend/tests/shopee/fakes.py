"""Servidor Shopee de mentira: valida a assinatura como o real faria e responde GraphQL."""

import hashlib
import json
from collections.abc import Callable

import httpx

APP_ID = "123456"
SECRET = "segredo-de-teste"


def signature_ok(request: httpx.Request) -> bool:
    header = request.headers.get("Authorization", "")
    parts = dict(p.strip().split("=", 1) for p in header.removeprefix("SHA256 ").split(","))
    body = request.content.decode()
    expected = hashlib.sha256(
        f"{parts['Credential']}{parts['Timestamp']}{body}{SECRET}".encode()
    ).hexdigest()
    return parts["Credential"] == APP_ID and parts["Signature"] == expected


def error(code: int, message: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"errors": [{"message": f"error [{code}]: {message}", "extensions": {"code": code}}]},
    )


class FakeShopee:
    """Despacha por nome da operação. `handlers[operação](variables, call_number)`."""

    def __init__(self, **handlers: Callable) -> None:
        self.handlers = handlers
        self.calls: list[dict] = []
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not signature_ok(request):
            return error(10020, "Invalid Signature")
        body = json.loads(request.content)
        query = body["query"]
        operation = next(
            (op for op in self.handlers if op in query),
            None,
        )
        self.calls.append(
            {"operation": operation, "query": query, "variables": body.get("variables", {})}
        )
        if operation is None:
            return error(11000, f"operação não prevista no teste: {query[:60]}")
        count = sum(1 for c in self.calls if c["operation"] == operation)
        result = self.handlers[operation](body.get("variables", {}), count)
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json={"data": result})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))
