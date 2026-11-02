"""Assinatura da Shopee Affiliate Open API (UNKNOWN-2, validado).

    Authorization: SHA256 Credential={AppId}, Signature={sig}, Timestamp={ts}
    Signature = SHA256( AppId + Timestamp + Payload + AppSecret )

O Payload é o corpo HTTP **exato**: a assinatura é sobre os mesmos bytes que vão no
request. Por isso quem chama serializa UMA vez e envia essa string — serializar de novo
(ou deixar o cliente HTTP fazê-lo) pode mudar a ordem/espaços e invalida a assinatura.
"""

import hashlib


class ShopeeAuth:
    def __init__(self, app_id: str, secret: str) -> None:
        if not app_id or not secret:
            raise ValueError("SHOPEE_APP_ID e SHOPEE_SECRET são obrigatórios")
        self._app_id = app_id
        self._secret = secret

    def signature(self, payload: str, timestamp: int) -> str:
        message = f"{self._app_id}{timestamp}{payload}{self._secret}"
        return hashlib.sha256(message.encode()).hexdigest()

    def header(self, payload: str, timestamp: int) -> str:
        return (
            f"SHA256 Credential={self._app_id}, Signature={self.signature(payload, timestamp)}, "
            f"Timestamp={timestamp}"
        )
