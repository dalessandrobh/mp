"""Pacote diário de conteúdo orgânico: um pin por produto do portfólio (título, descrição, link
de destino rastreado e imagem, na ordem em que o formulário de criar pin os pede).

O dono publica à mão; o MP prepara tudo. Regras que não mudam com o provedor de texto:

- Só fatos da API entram no texto (título, preço, vendas, nota). Número que não esteja nos
  fatos reprova a legenda do LLM, que então cai no modelo de texto (template).
- O aviso de afiliado é acrescentado pelo código, nunca pelo LLM.
- A palavra "Shopee" nunca aparece no texto nem nas hashtags: os Termos de Afiliados (2.3(a))
  vedam marca/nome da Shopee na mídia de afiliado.
- Cada post tem o próprio `creative` e o próprio link (sub_id com o id do criativo, canal
  `pin`): a venda volta ao post exato. O id do criativo ocupa 2 dígitos base36 no sub_id,
  logo há 1295 posts por produto-dia... na prática, por instalação: ao passar disso o link
  falha alto (nunca atribui errado).
- Toda chamada ao LLM vai para `llm_calls`; o teto diário em USD vale antes de cada chamada.
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.llm.base import LLMAdapter, LLMError
from app.adapters.marketplace.base import MarketplaceAdapter
from app.adapters.social.base import fit
from app.domain.enums import ProductState
from app.models.ai import LlmCall
from app.models.catalog import Category, Marketplace, Product
from app.models.content import Creative
from app.models.tracking import AffiliateLink
from app.services import ev_scoring, tracking_service
from app.services._funnel_queries import latest_snapshot, products_in_state

TZ = ZoneInfo("America/Sao_Paulo")
FORMAT = "organic_post"
# Canal do link do pacote diário = onde a pessoa realmente posta. Hoje é o Pinterest, e o
# clique precisa entrar como `pin`: com `ig` todo clique do Pinterest seria creditado ao
# Instagram e a CVR por canal viraria uma média sem significado. É o mesmo canal da
# publicação automática (publishing_service), então o orgânico manual de hoje e o aprovado de
# amanhã caem no mesmo balde. Quando o Instagram entrar de verdade, ele ganha o próprio canal.
CHANNEL = "pin"
ELIGIBLE_STATES = (ProductState.WINNER, ProductState.ACTIVE, ProductState.TEST)
DISCLOSURE = (
    "🔗 Link de afiliado: posso receber comissão se você comprar por ele, "
    "sem custo extra para você. #publi"
)
# Limites do pin (API v5 e formulário): título 100 e descrição 800 caracteres. A legenda do
# modelo fica menor que a descrição porque a divulgação de afiliado e as hashtags entram
# depois e não podem ser cortadas.
MAX_PIN_TITLE = 100
MAX_PIN_DESCRIPTION = 800
# O Pinterest limita o nome do board a 50 caracteres.
MAX_BOARD_NAME = 50
MAX_CAPTION = 600
MAX_TOKENS = 500

# Promessas que a legenda não pode fazer (não estão nos fatos da API).
_BANNED = re.compile(
    r"garantid|milagr|cura\b|curar|100\s*%|sem riscos?|frete gr[aá]tis|[uú]ltimas? unidades|"
    r"estoque|acaba hoje|menor pre[cç]o|melhor do mundo|aprovado pela anvisa|shopee",
    re.I,
)

SYSTEM = (
    "Você escreve descrições curtas de pin do Pinterest em português do Brasil para um "
    "afiliado de marketplace. Regras: use SOMENTE os fatos fornecidos; não invente números, "
    "benefícios, estoque, frete, prazos nem promoções; diga o que o produto é e para que "
    "serve, com as palavras que alguém digitaria na busca; tom natural de quem indica um "
    "produto, sem exagero; não peça curtidas, comentários nem salvamentos; a primeira linha "
    "é um gancho de uma frase e a descrição tem no máximo 500 caracteres; sem hashtags no "
    "texto e sem link (o código acrescenta). Responda APENAS um JSON: "
    '{"hook": "...", "caption": "...", "hashtags": ["...", "..."]} com 3 a 5 hashtags, '
    "sem o símbolo #. Nunca escreva a palavra Shopee."
)


@dataclass
class ContentResult:
    created: int = 0
    llm_used: int = 0
    template_used: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    packages: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- fatos


def _brl(value: Decimal) -> str:
    whole, cents = f"{value:.2f}".split(".")
    return f"R$ {int(whole):,}".replace(",", ".") + f",{cents}"


_BRAND = re.compile(r"\bshopee\w*", re.I)


def _without_brand(text: str) -> str:
    """Tira a marca do texto (títulos de anúncio às vezes a trazem)."""
    return " ".join(_BRAND.sub("", text).split())


def _facts(product: Product, snapshot) -> dict:
    facts: dict = {"produto": _without_brand(product.title)}
    if snapshot is not None:
        if snapshot.price is not None:
            facts["preco"] = _brl(snapshot.price)
        if snapshot.sales_volume:
            facts["vendidos"] = f"{snapshot.sales_volume:,}".replace(",", ".")
        if snapshot.rating:
            facts["nota"] = f"{snapshot.rating:.1f}".replace(".", ",")
    if product.category_path:
        facts["categoria"] = " > ".join(product.category_path)
    return facts


def _short_title(title: str, limit: int = 70) -> str:
    title = " ".join(title.split())
    if len(title) <= limit:
        return title
    return title[:limit].rsplit(" ", 1)[0].rstrip(",.-– ") + "…"


def _hashtag(text: str) -> str | None:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    word = re.sub(r"[^a-z0-9]", "", ascii_text.lower())
    return f"#{word}" if 3 <= len(word) <= 30 else None


def _hashtags(
    product: Product, extra: list[str] | None = None, category_name: str | None = None
) -> list[str]:
    """Hashtags a partir do texto, nunca de ids.

    O caminho de categoria da Shopee é uma lista de IDs numéricos (`["100637", "100725"]`);
    virar hashtag daria `#100637`, que não significa nada para quem busca. O nome da categoria
    de nível 1 entra no lugar, e qualquer item só numérico do caminho é descartado.
    """
    tags: list[str] = []
    path = [str(item) for item in (product.category_path or []) if not str(item).isdigit()]
    for source in [*(extra or []), *([category_name] if category_name else []), *reversed(path)]:
        tag = _hashtag(source)
        if tag and "shopee" not in tag and tag not in tags:
            tags.append(tag)
    for fixed in ("#achadinhos", "#indicacao"):
        if fixed not in tags:
            tags.append(fixed)
    return tags[:5]


def _template(facts: dict) -> tuple[str, str]:
    """(gancho, legenda) só com fatos."""
    name = _short_title(facts["produto"])
    hook = f"Olha esse achado: {name}"
    lines = [hook]
    details = []
    if "preco" in facts:
        details.append(f"por {facts['preco']}")
    if "vendidos" in facts:
        details.append(f"{facts['vendidos']} vendidos")
    if "nota" in facts:
        details.append(f"nota {facts['nota']}")
    if details:
        lines.append("📌 " + " · ".join(details[:3]))
    lines.append("Salve este pin para ver depois.")
    return hook, "\n\n".join(lines)


def _category_name(db: Session, product: Product, marketplace_code: str) -> str | None:
    """Nome da categoria de nível 1, sem a marca do marketplace; None se não houver nome."""
    if not product.category_path:
        return None
    raw = str(product.category_path[0])
    if raw.isdigit():
        name = db.execute(
            select(Category.name).where(
                Category.marketplace == marketplace_code,
                Category.external_id == raw,
                Category.level == 1,
            )
        ).scalar_one_or_none()
    else:
        name = raw  # o mock já devolve o nome
    return (_without_brand(name) or None) if name else None


def _board_name(category_name: str | None) -> str | None:
    """Board sugerido = categoria de nível 1 do produto, sempre com o mesmo nome.

    A estabilidade é o ponto: pins do mesmo assunto no mesmo board é o que dá ao board um
    tema legível para o Pinterest (e para quem entra no perfil). Daí o nome vir da categoria
    e não do produto. Sem nome de categoria conhecido devolve None: sugerir "Categoria
    100637" seria pior que não sugerir nada.
    """
    return fit(category_name, MAX_BOARD_NAME) if category_name else None


def _video_script(facts: dict) -> str:
    """Roteiro de vídeo curto (cerca de 15 s) para a pessoa gravar com o produto na mão.

    Só usa fatos já conhecidos e não promete nada além deles. O vídeo é feito pela própria
    pessoa: reaproveitar vídeo de vendedor traz direito autoral e marca de terceiros.
    """
    name = _short_title(facts["produto"], 40)
    details = []
    if "preco" in facts:
        details.append(facts["preco"])
    if "nota" in facts:
        details.append(f"nota {facts['nota']}")
    if "vendidos" in facts:
        details.append(f"{facts['vendidos']} vendidos")
    numbers = " · ".join(details[:3])
    middle = f"Texto na tela: {numbers}\n" if numbers else ""
    return (
        f"1) 0–3 s: produto em primeiro plano, bem iluminado. Texto na tela: {name}\n"
        f"2) 3–10 s: mostre de perto e em uso, mexendo no produto.\n{middle}"
        "3) 10–15 s: feche com o produto parado e o texto \"Link no pin\".\n"
        "Dicas: vertical (9:16), luz natural, sem música com direitos, sem mostrar caixa ou "
        "etiqueta com marca de loja; fale só o que você vê, sem prometer resultado. "
        "Confira o preço no link antes de postar, ele muda."
    )


def _pin_description(caption: str, tags: str) -> str:
    """Descrição do pin: legenda + divulgação + hashtags, nunca acima de 800 caracteres.

    A divulgação e as hashtags têm o orçamento reservado ANTES de cortar a legenda: se o
    texto estourar, quem se perde é o fim da legenda, nunca o aviso de afiliado.
    """
    tail = f"\n\n{DISCLOSURE}\n\n{tags}"
    budget = max(MAX_PIN_DESCRIPTION - len(tail), 1)
    # `fit` normaliza espaços (e portanto apaga as quebras de linha): só entra quando é
    # preciso cortar. Legenda que cabe mantém os parágrafos como foram escritos.
    body = caption if len(caption) <= budget else fit(caption, budget)
    return f"{body}{tail}"


# ---------------------------------------------------------------- LLM


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+", text))


def _validate(parsed: dict, facts: dict) -> tuple[str, str, list[str]]:
    hook = str(parsed.get("hook", "")).strip()
    caption = str(parsed.get("caption", "")).strip()
    tags = parsed.get("hashtags") or []
    if not hook or not caption:
        raise ValueError("gancho ou legenda vazios")
    if len(caption) > MAX_CAPTION:
        raise ValueError("legenda longa demais")
    text = f"{hook} {caption}"
    if _BANNED.search(text):
        raise ValueError("promessa fora dos fatos")
    allowed = _numbers(" ".join(str(v) for v in facts.values()))
    stray = _numbers(text) - allowed
    if stray:
        raise ValueError(f"número fora dos fatos: {sorted(stray)[:3]}")
    if "http" in text.lower() or "#" in text:
        raise ValueError("link ou hashtag dentro da legenda")
    if not isinstance(tags, list):
        raise ValueError("hashtags inválidas")
    return hook, caption, [str(t) for t in tags]


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?|```$", "", cleaned, flags=re.M).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("resposta sem JSON")
    return json.loads(cleaned[start : end + 1])


def _spent_today_usd(db: Session, now: datetime) -> Decimal:
    start = datetime.combine(now.astimezone(TZ).date(), datetime.min.time(), TZ)
    total = db.execute(
        select(func.coalesce(func.sum(LlmCall.cost_usd), 0)).where(LlmCall.created_at >= start)
    ).scalar_one()
    return Decimal(total)


def _try_llm(
    db: Session, llm: LLMAdapter, facts: dict, *, cap_usd: Decimal, now: datetime
) -> tuple[str, str, list[str], int] | str:
    """(gancho, legenda, hashtags, llm_call_id) ou o motivo de ter caído no template."""
    if _spent_today_usd(db, now) >= cap_usd:
        return "teto diário de custo do LLM atingido"
    prompt = "Fatos do produto (JSON):\n" + json.dumps(facts, ensure_ascii=False)
    call = LlmCall(
        purpose="creative_copy", provider=llm.provider, model=llm.model, prompt=prompt,
        success=False,
    )
    try:
        result = llm.generate(system=SYSTEM, prompt=prompt, max_tokens=MAX_TOKENS)
    except LLMError as exc:
        call.error = str(exc)[:500]
        db.add(call)
        db.flush()
        return f"LLM indisponível: {exc}"[:200]
    call.model, call.response = result.model, result.text
    call.input_tokens, call.output_tokens = result.input_tokens, result.output_tokens
    call.cost_usd, call.latency_ms = result.cost_usd, result.latency_ms
    db.add(call)
    try:
        hook, caption, tags = _validate(_parse_json(result.text), facts)
    except (ValueError, json.JSONDecodeError) as exc:
        call.error = f"reprovado: {exc}"[:500]
        db.flush()
        return f"legenda do LLM reprovada ({exc})"
    call.success = True
    db.flush()
    return hook, caption, tags, call.id


# ---------------------------------------------------------------- pacote


def _eligible(
    db: Session, adapter: MarketplaceAdapter, now: datetime, *, min_days_between: int = 0
) -> list[Product]:
    own = db.execute(
        select(Marketplace.id).where(Marketplace.code == adapter.code)
    ).scalar_one_or_none()
    start = datetime.combine(now.astimezone(TZ).date(), datetime.min.time(), TZ)
    # Produto já divulgado há menos de `min_days_between` dias fica de fora (hoje inclusive:
    # 0 só impede repetir no mesmo dia). Postado no dia D volta no dia D + min_days_between.
    # Repetir o mesmo pin em dias seguidos parece spam e gasta o alcance da conta.
    cutoff = start - timedelta(days=max(min_days_between - 1, 0))
    done_today = set(
        db.execute(
            select(Creative.product_id).where(
                Creative.format == FORMAT, Creative.created_at >= cutoff
            )
        ).scalars()
    )
    posts = dict(
        db.execute(
            select(Creative.product_id, func.count()).where(Creative.format == FORMAT)
            .group_by(Creative.product_id)
        ).all()
    )
    candidates: list[Product] = []
    for state in ELIGIBLE_STATES:
        candidates.extend(
            p for p in products_in_state(db, state)
            if p.marketplace_id == own and p.image_url and p.id not in done_today
        )
    # Ordem dos slots do dia: primeiro quem NUNCA foi divulgado, depois maior receita
    # esperada por clique.
    #
    # Essa é a regra de exploração desta fase, e é deliberada: um produto sem nenhum post
    # não tem clique, logo não tem CVR medido, logo o EV dele é prior puro. Publicar por
    # EV antes de medir seria perseguir uma hipótese. Quando o Thompson sampling entrar
    # (docs/plano-10k.md §3.4), ele substitui estas duas chaves por um sorteio da posterior
    # — que faz a mesma coisa, só continuamente em vez de em dois degraus.
    evs = ev_scoring.latest_evs(db)

    def rank(product: Product):
        ev = evs.get(product.id)
        never_posted = posts.get(product.id, 0) == 0
        return (
            not never_posted,
            posts.get(product.id, 0) if never_posted else 0,
            ev is None,
            -(ev.ev_per_click if ev else 0),
            product.id,
        )

    return sorted(candidates, key=rank)


def generate_daily_package(
    db: Session,
    adapter: MarketplaceAdapter,
    llm: LLMAdapter | None,
    *,
    count: int,
    max_sub_id_length: int,
    llm_cap_usd: Decimal,
    public_base: str = "",
    min_days_between: int = 0,
    now: datetime | None = None,
) -> ContentResult:
    now = now or datetime.now(UTC)
    result = ContentResult()
    for product in _eligible(db, adapter, now, min_days_between=min_days_between)[:count]:
        snapshot = latest_snapshot(db, product.id)
        facts = _facts(product, snapshot)

        hook, caption = _template(facts)
        extra_tags: list[str] = []
        generated_by, llm_call_id = "template", None
        if llm is not None:
            attempt = _try_llm(db, llm, facts, cap_usd=llm_cap_usd, now=now)
            if isinstance(attempt, str):
                result.warnings.append(f"produto {product.id}: {attempt}; usei o modelo de texto")
            else:
                hook, body, extra_tags, llm_call_id = attempt
                caption = f"{hook}\n\n{body}"  # o gancho abre a legenda
                generated_by = f"llm:{llm.model}"

        creative = Creative(
            product_id=product.id, format=FORMAT, headline=hook, primary_text=caption,
            call_to_action="Link de destino do pin",
            asset_urls=[product.image_url], generated_by=generated_by, llm_call_id=llm_call_id,
        )
        db.add(creative)
        db.flush()

        links = tracking_service.generate_links(
            db, adapter, channel=CHANNEL, max_sub_id_length=max_sub_id_length,
            creative_id=creative.id, only_product_ids={product.id},
        )
        link = db.execute(
            select(AffiliateLink).where(
                AffiliateLink.product_id == product.id, AffiliateLink.creative_id == creative.id,
                AffiliateLink.channel == CHANNEL,
            )
        ).scalar_one_or_none()
        if link is None or not link.short_url:
            # Sem link rastreado não há pacote: o post sem atribuição não serve.
            result.skipped += 1
            result.warnings.extend(links.warnings or [f"produto {product.id}: sem link"])
            db.delete(creative)
            db.flush()
            continue

        category_name = _category_name(db, product, adapter.code)
        tags = " ".join(_hashtags(product, extra_tags, category_name))
        title = _short_title(facts["produto"], MAX_PIN_TITLE)
        description = _pin_description(caption, tags)
        # O link que vai para o post é o NOSSO redirect, não o link de afiliado: é ele que
        # conta o clique (sem clique não há CVR) e é ele que mantém a URL com o ID de
        # afiliado fora de qualquer página indexável (Termos 4.3(k)).
        tracked_url = f"{public_base}/go/{link.sub_id}" if public_base else link.short_url
        if not public_base:
            result.warnings.append(
                "PUBLIC_BASE_URL não configurada: o post sai com o link direto e o clique "
                "NÃO será medido"
            )
        board = _board_name(category_name)
        board_line = f"*Board sugerido (onde salvar):*\n{board}\n\n" if board else ""

        # Os campos, na ordem em que o formulário de criar pin os pede.
        message = (
            f"📌 *Pin do dia — {_short_title(facts['produto'], 50)}*\n\n"
            f"{board_line}"
            f"*Título do pin:*\n{title}\n\n"
            f"*Descrição (copie e cole):*\n{description}\n\n"
            f"*Link de destino (campo \"Link\" do pin):*\n{tracked_url}"
        )
        if product.image_url:
            message += f"\n\n*Imagem (salve e envie no pin):*\n{product.image_url}"
        message += f"\n\n*Roteiro de vídeo (opcional, 15 s):*\n{_video_script(facts)}"
        result.created += 1
        result.llm_used += generated_by != "template"
        result.template_used += generated_by == "template"
        result.packages.append(
            {
                "product_id": product.id, "creative_id": creative.id, "sub_id": link.sub_id,
                "image_url": product.image_url, "caption": message, "generated_by": generated_by,
                "tracked_url": tracked_url, "title": title, "description": description,
                "board": board, "video_script": _video_script(facts),
            }
        )
    return result
