"""Persistência do token OAuth que rotaciona, isolada da transação de quem usa.

O problema que esta classe existe para resolver, e que não é óbvio:

O refresh token do Pinterest rotaciona. Quando renovamos, o Pinterest devolve um token
novo e **invalida o antigo do lado dele**. Se o token novo fosse gravado na mesma
transação da publicação e a publicação falhasse, o rollback jogaria o token novo fora —
e o antigo já não vale. O sistema ficaria com um token morto, e a única saída seria
reautorizar no navegador à mão.

Por isso `save` abre uma sessão PRÓPRIA e commita na hora, independente de quem chamou.
O custo é que um token é gravado mesmo que a publicação depois falhe; o ganho é que isso
é inofensivo (token válido gravado) enquanto o inverso é fatal (token válido perdido).

`load` lê pela sessão de quem chamou, e cai para `seed_refresh_token` (o valor do
ambiente) quando a tabela ainda está vazia — é o caminho de primeira autorização.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.adapters.social.pinterest.auth import StoredToken
from app.models.social import OauthToken

logger = logging.getLogger(__name__)

PINTEREST = "pinterest"


def _epoch(value: datetime | None) -> float | None:
    return value.timestamp() if value else None


def _moment(value: float | None) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if value else None


class TokenStore:
    def __init__(
        self,
        db: Session,
        session_factory,
        *,
        provider: str = PINTEREST,
        seed_refresh_token: str = "",
    ) -> None:
        self._db = db
        self._session_factory = session_factory
        self._provider = provider
        self._seed = seed_refresh_token

    def load(self) -> StoredToken | None:
        row = self._db.get(OauthToken, self._provider)
        if row is None:
            if not self._seed:
                return None
            return StoredToken(refresh_token=self._seed)
        return StoredToken(
            refresh_token=row.refresh_token,
            access_token=row.access_token,
            access_expires_at=_epoch(row.access_expires_at),
            refresh_expires_at=_epoch(row.refresh_expires_at),
        )

    def save(self, token: StoredToken, *, scope: str | None = None) -> None:
        """Commita em sessão própria: perder um refresh token rotacionado é irreversível.

        `scope` só é gravado quando informado (a autorização inicial). A renovação, que
        chama `save(token)` sem escopo, não apaga o que já estava gravado.
        """
        session = self._session_factory()
        try:
            row = session.get(OauthToken, self._provider)
            if row is None:
                row = OauthToken(provider=self._provider, refresh_token=token.refresh_token)
                session.add(row)
            row.refresh_token = token.refresh_token
            row.access_token = token.access_token
            row.access_expires_at = _moment(token.access_expires_at)
            row.refresh_expires_at = _moment(token.refresh_expires_at)
            if scope is not None:
                row.scope = scope
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("falha ao gravar o token de %s", self._provider)
            raise
        finally:
            session.close()
        # A sessão de quem chamou pode ter a linha velha em cache.
        cached = self._db.get(OauthToken, self._provider)
        if cached is not None:
            self._db.expire(cached)
