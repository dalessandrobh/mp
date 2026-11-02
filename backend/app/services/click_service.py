"""Clique no redirect próprio: medição, deduplicação e agregação.

Três decisões que sustentam a estatística do funil orgânico:

* **Pré-visualizador de link não é clique.** WhatsApp, Facebook, Telegram e afins buscam
  a URL para montar o card da mensagem. Esse acesso acontece sempre e nunca compra: contado
  como clique, derruba o CVR de todo produto compartilhado e o aprendizado persegue ruído.
  Fica gravado com `is_bot=True` — não se joga dado fora, só se tira da conta.
* **O mesmo visitante no mesmo dia conta uma vez.** Quem abre o link, volta e abre de novo
  é um clique para efeito de CVR. `is_unique` marca o primeiro.
* **O IP nunca é gravado.** `visitor_hash` = sha256(ip + user-agent + sal + dia) truncado.
  Deduplica e não volta ao IP. O sal muda o hash entre instalações.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.tracking import AffiliateLink, LinkClick

TZ = ZoneInfo("America/Sao_Paulo")

# Buscadores de pré-visualização e crawlers. Lista conservadora: o custo de marcar humano
# como bot é perder um clique da amostra; o de marcar bot como humano é poluir todo o CVR.
_BOT = re.compile(
    r"bot|crawler|spider|crawling|slurp|preview|fetcher|scraper|monitor|"
    r"facebookexternalhit|facebookcatalog|whatsapp|telegram|twitterbot|discord|slack|"
    r"linkedinbot|pinterest|skypeuripreview|vkshare|redditbot|embedly|quora|outbrain|"
    r"googlebot|bingbot|yandex|duckduck|applebot|petalbot|ahrefs|semrush|mj12|dotbot|"
    r"headless|phantomjs|puppeteer|playwright|selenium|"
    r"curl/|wget/|python-requests|python-httpx|httpie|go-http-client|java/|okhttp|axios/",
    re.I,
)

MAX_USER_AGENT = 400
MAX_REFERRER = 400


@dataclass(frozen=True)
class ClickRecord:
    link_id: int
    product_id: int
    channel: str
    is_bot: bool
    is_unique: bool


def is_bot(user_agent: str | None) -> bool:
    """Sem user-agent também é bot: navegador real sempre manda um."""
    if not user_agent or not user_agent.strip():
        return True
    return bool(_BOT.search(user_agent))


def visitor_hash(ip: str | None, user_agent: str | None, *, salt: str, day: date) -> str | None:
    """None quando não há nada para identificar — então o clique não deduplica."""
    if not ip and not user_agent:
        return None
    raw = f"{ip or ''}|{user_agent or ''}|{salt}|{day.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def find_link(db: Session, sub_id: str) -> AffiliateLink | None:
    """Só vale sub_id que nós emitimos e não revogamos.

    O destino sai do banco, nunca da requisição: é o que impede o redirect de virar um
    open redirect para qualquer URL que alguém queira pendurar no nosso domínio.
    """
    return db.execute(
        select(AffiliateLink).where(
            AffiliateLink.sub_id == sub_id, AffiliateLink.revoked_at.is_(None)
        )
    ).scalar_one_or_none()


def record_click(
    db: Session,
    link: AffiliateLink,
    *,
    ip: str | None,
    user_agent: str | None,
    referrer: str | None,
    salt: str,
    now: datetime | None = None,
) -> ClickRecord:
    day = (now or datetime.now(TZ)).astimezone(TZ).date()
    bot = is_bot(user_agent)
    fingerprint = visitor_hash(ip, user_agent, salt=salt, day=day)

    unique = True
    if fingerprint is not None:
        seen = db.execute(
            select(LinkClick.id).where(
                LinkClick.affiliate_link_id == link.id,
                LinkClick.click_date == day,
                LinkClick.visitor_hash == fingerprint,
            ).limit(1)
        ).first()
        unique = seen is None

    db.add(
        LinkClick(
            affiliate_link_id=link.id,
            product_id=link.product_id,
            channel=link.channel,
            click_date=day,
            visitor_hash=fingerprint,
            user_agent=(user_agent or None) and user_agent[:MAX_USER_AGENT],
            referrer=(referrer or None) and referrer[:MAX_REFERRER],
            is_bot=bot,
            is_unique=unique,
        )
    )
    db.flush()
    return ClickRecord(
        link_id=link.id,
        product_id=link.product_id,
        channel=link.channel,
        is_bot=bot,
        is_unique=unique,
    )


def clicks_by_day(
    db: Session, *, since: date, until: date
) -> dict[tuple[date, int, str], dict[str, int]]:
    """{(dia, produto, canal): {clicks, raw_clicks}}.

    `clicks` é o que a estatística usa: humano e único. `raw_clicks` fica ao lado para
    diagnóstico — a diferença entre os dois é a fatia de pré-visualização do canal, e ver
    essa fatia subir é como se descobre que um canal virou vitrine de robô.
    """
    rows = db.execute(
        select(
            LinkClick.click_date,
            LinkClick.product_id,
            LinkClick.channel,
            func.count().label("raw"),
            func.count().filter(~LinkClick.is_bot, LinkClick.is_unique).label("human"),
        )
        .where(LinkClick.click_date >= since, LinkClick.click_date <= until)
        .group_by(LinkClick.click_date, LinkClick.product_id, LinkClick.channel)
    ).all()
    return {
        (day, product_id, channel): {"clicks": int(human), "raw_clicks": int(raw)}
        for day, product_id, channel, raw, human in rows
    }
