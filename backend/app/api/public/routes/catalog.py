"""Página pública de links ("link na bio"), em `/l`.

Por que ela existe, e não um link de afiliado direto na bio:

1. **Medição.** Todo clique passa pelo nosso `/go/{sub_id}` e vira linha em `link_clicks`.
   Sem isso não há CVR, e sem CVR não há aprendizado estatístico nenhum.
2. **Conformidade.** Os Termos de Afiliados 4.3(k) proíbem que uma URL com o ID de
   afiliado seja indexada. O pin do Pinterest e o link da bio apontam para esta página,
   que é `noindex`; o link de afiliado só aparece depois do clique, em um 302.
3. **Vitrine.** Um perfil tem uma linha de bio e dezenas de produtos.

Os Termos 2.3(a) proíbem marca, nome e logo do marketplace na mídia de afiliado: nada
disso aparece aqui, nem no título nem no texto do botão.
"""

from html import escape

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.public.routes.redirect import NO_INDEX
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.services import bio_service
from app.services.bio_service import BioItem

router = APIRouter(tags=["public"])

DISCLOSURE = (
    "Os links desta página são de afiliado: posso receber comissão se você comprar "
    "por eles, sem custo extra para você."
)

# Paleta em laranja e amarelo, inspirada nas cores da Shopee e num estilo de "achadinho" com
# etiquetas arredondadas. SÓ AS CORES E O CLIMA: nada de logo, nome, sacola, caixa, fonte ou
# selo ("Mall", "Frete grátis") do marketplace, nem o texto "já adiciona no carrinho" (a compra
# não acontece nesta página, e sugerir que sim enganaria quem chega). A página vende o produto
# de outra pessoa; se parecesse a loja oficial, enganaria (Termos da Shopee 2.3(a) e 4.3(j)),
# por isso o layout é próprio e o aviso de afiliado fica visível.
#
# Tampouco imita o Pinterest: nada de mosaico de alturas diferentes nem o vermelho dele
# (Diretrizes de Desenvolvedor 4.7: "replicating or imitating the visual design, layout, or
# user experience of Pinterest"). O título não promete frescor que a página não tem ("de
# hoje"): a vitrine é a seleção atual do portfólio, não a de um dia.
#
# O laranja puro (#EE4D2D) com texto branco dá 3,66:1, abaixo dos 4,5:1 de legibilidade. Por
# isso ele fica nos detalhes (faixa, bordas, foco) e botão, preço e etiqueta usam `strong`.
# Nenhuma fonte, imagem ou script externos: a política de privacidade promete que não há.
PALETTE = {
    "light": {
        "bg_top": "#FFF1EC",
        "bg_mid": "#FFE3DA",
        "bg_bottom": "#FFF7F3",
        "card": "#FFFFFF",
        "ink": "#222222",
        "muted": "#5E5E5E",
        "tint": "#FFF3EE",
        "line": "#F0D5CB",
        "orange": "#EE4D2D",
        "amber": "#F69113",
        "strong": "#C93012",
        "on_strong": "#FFFFFF",
        "yellow": "#FFC72C",
        "on_yellow": "#2B1B12",
        "coral": "#FF8A7A",
    },
    "dark": {
        "bg_top": "#1B1512",
        "bg_mid": "#2A1812",
        "bg_bottom": "#1B1512",
        "card": "#261D19",
        "ink": "#F5EDE9",
        "muted": "#B9A9A2",
        "tint": "#2E211B",
        "line": "#3A2B24",
        "orange": "#FF7A59",
        "amber": "#F69113",
        "strong": "#FF7A59",
        "on_strong": "#1B1512",
        "yellow": "#FFC72C",
        "on_yellow": "#2B1B12",
        "coral": "#FF8A7A",
    },
}

TAGLINE = "Olha o que eu encontrei"


def _vars(theme: dict[str, str]) -> str:
    return "".join(f"--{key.replace('_', '-')}:{value};" for key, value in theme.items())


STYLE = (
    f":root{{color-scheme:light dark;{_vars(PALETTE['light'])}}}"
    f"@media(prefers-color-scheme:dark){{:root{{{_vars(PALETTE['dark'])}}}}}"
    + """
*{box-sizing:border-box;margin:0;padding:0}
body{background:linear-gradient(180deg,var(--bg-top) 0,var(--bg-mid) 38%,var(--bg-bottom) 100%)
fixed;color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,
sans-serif;min-height:100vh}
body::before{content:"";display:block;height:6px;
background:linear-gradient(90deg,var(--orange),var(--amber))}
.wrap{max-width:960px;margin:0 auto;padding:28px 16px 48px}
header{text-align:center;margin-bottom:22px;position:relative}
header::before,header::after{content:"✦" / "";position:absolute;color:var(--amber);
font-size:1.6rem;line-height:1}
header::before{left:6%;top:6px}
header::after{right:8%;top:58px;color:var(--coral);font-size:1.2rem}
h1{display:flex;flex-direction:column;align-items:center;gap:6px;
font-family:Impact,Haettenschweiler,"Arial Narrow Bold","Helvetica Neue Condensed Bold",
system-ui,sans-serif;font-weight:900;text-transform:uppercase;letter-spacing:.02em;
line-height:1;font-size:clamp(2.1rem,9vw,3.3rem)}
.pill{display:inline-block;padding:.12em .55em .08em;border-radius:.45em}
.pill.a{background:var(--yellow);color:var(--on-yellow);transform:rotate(-2deg)}
.pill.b{background:var(--strong);color:var(--on-strong);transform:rotate(1.5deg)}
.tagline{margin-top:14px;font-family:Impact,Haettenschweiler,"Arial Narrow Bold",system-ui,
sans-serif;font-size:1.35rem;text-transform:uppercase;letter-spacing:.03em;
text-decoration:underline wavy var(--orange);text-underline-offset:7px;
text-decoration-thickness:2px}
.sub{color:var(--muted);font-size:.98rem;margin-top:12px}
.note{background:var(--tint);border:1px solid var(--line);border-left:4px solid var(--orange);
border-radius:12px;color:var(--ink);font-size:.85rem;padding:12px 14px;margin:0 auto 24px;
max-width:640px}
ul{list-style:none;display:grid;gap:16px;grid-template-columns:1fr}
@media(min-width:600px){ul{grid-template-columns:repeat(2,1fr)}}
@media(min-width:900px){ul{grid-template-columns:repeat(3,1fr)}}
li{display:flex}
a.card{display:flex;flex-direction:column;width:100%;background:var(--card);
border:1px solid var(--line);border-radius:18px;overflow:hidden;text-decoration:none;
color:inherit;transition:border-color .15s,box-shadow .15s}
a.card:hover{border-color:var(--orange);box-shadow:0 6px 18px rgba(238,77,45,.18)}
a.card:focus-visible{outline:3px solid var(--orange);outline-offset:2px}
img{display:block;width:100%;aspect-ratio:1/1;object-fit:cover;background:var(--tint)}
.info{display:flex;flex-direction:column;flex:1;gap:8px;padding:14px}
.title{font-size:.95rem;font-weight:500;display:-webkit-box;-webkit-line-clamp:2;
-webkit-box-orient:vertical;overflow:hidden;min-height:2.85em}
.meta{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:.84rem;color:var(--muted)}
.star{color:var(--amber)}
.rate{font-weight:600;color:var(--ink)}
.price{color:var(--strong);font-size:1.25rem;font-weight:800}
.cta{margin-top:auto;background:var(--strong);color:var(--on-strong);text-align:center;
font-weight:700;font-size:.92rem;padding:11px 14px;border-radius:999px}
.empty{color:var(--muted);text-align:center;padding:48px 0}
footer{color:var(--muted);font-size:.78rem;text-align:center;margin-top:32px}
"""
)


def _headline(title: str) -> str:
    """Primeira palavra na etiqueta amarela, o resto na laranja (com o coração).

    Título de uma palavra só fica só na amarela. O coração é decoração, fora do que um leitor
    de tela lê.
    """
    first, _, rest = " ".join(title.split()).partition(" ")
    pills = f'<span class="pill a">{escape(first)}</span>'
    if rest:
        pills += f'<span class="pill b">{escape(rest)} <span aria-hidden="true">♥</span></span>'
    return pills


def _meta(item: BioItem) -> str:
    """Nota e vendas, como a loja informa. Dado ausente (ou zero) simplesmente não aparece.

    "Vendidos" e não "já vendeu": o número é uma janela móvel que também diminui (medido em
    produção), não um acumulado — então não dá para prometer o total de todos os tempos. A
    contagem de avaliações vem vazia em 100% dos produtos, por isso só a nota é mostrada.
    """
    parts: list[str] = []
    if item.rating is not None:
        note = f"{item.rating:.1f}".replace(".", ",")
        parts.append(
            f'<span class="rate" aria-label="Nota {note} de 5">'
            f'<span class="star" aria-hidden="true">★</span> <span aria-hidden="true">{note}</span>'
            "</span>"
        )
    if item.sales_volume:
        sold = f"{item.sales_volume:,}".replace(",", ".")
        parts.append(f'<span class="sold">{sold} vendidos</span>')
    return f'<div class="meta">{"".join(parts)}</div>' if parts else ""


def _price(item: BioItem) -> str:
    if item.price is None:
        return ""
    value = f"{item.price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f'<div class="price">R$ {value}</div>'


def _card(item: BioItem) -> str:
    image = (
        f'<img src="{escape(item.image_url, quote=True)}" alt="" loading="lazy" '
        f'referrerpolicy="no-referrer">'
        if item.image_url
        else '<img alt="" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///'
        'yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">'
    )
    return (
        f'<li><a class="card" href="/go/{escape(item.sub_id, quote=True)}" '
        f'rel="nofollow noopener sponsored" target="_blank">{image}'
        f'<div class="info"><div class="title">{escape(item.title)}</div>'
        f'{_meta(item)}{_price(item)}<span class="cta">Ver oferta →</span></div></a></li>'
    )


def render(items: list[BioItem], *, title: str, subtitle: str) -> str:
    body = (
        "<ul>" + "".join(_card(i) for i in items) + "</ul>"
        if items
        else '<p class="empty">Nenhuma indicação publicada agora. Volte mais tarde.</p>'
    )
    return (
        "<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        # Os Termos 4.3(k) proíbem indexar URL com ID de afiliado: esta página leva a elas.
        '<meta name="robots" content="noindex, nofollow, noarchive">'
        '<meta name="referrer" content="no-referrer">'
        f'<meta name="theme-color" content="{PALETTE["light"]["orange"]}">'
        f"<title>{escape(title)}</title><style>{STYLE}</style></head><body><div class=\"wrap\">"
        f"<header><h1>{_headline(title)}</h1>"
        f'<p class="tagline">{escape(TAGLINE)}</p>'
        f'<p class="sub">{escape(subtitle)}</p></header>'
        f'<p class="note">{escape(DISCLOSURE)}</p>{body}'
        "<footer>Preços, vendas e notas são informados pela loja e mudam sem aviso; "
        "confira na página do produto."
        "</footer></div></body></html>"
    )


def _page(db: Session, settings: Settings, *, prefer_channel: str | None) -> Response:
    html = render(
        bio_service.bio_items(db, prefer_channel=prefer_channel),
        title=settings.bio_page_title,
        subtitle=settings.bio_page_subtitle,
    )
    return Response(content=html, media_type="text/html; charset=utf-8", headers=NO_INDEX)


# HEAD além de GET: validadores de URL (como o campo "Site" do perfil do Pinterest) costumam
# conferir o endereço com HEAD, e um 405 ali parece página inexistente.
@router.api_route("/l", methods=["GET", "HEAD"], include_in_schema=False)
def bio_page(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    return _page(db, settings, prefer_channel=None)


# Com e sem a barra final: o campo "Site" do Pinterest (e muito navegador) normaliza o
# endereço acrescentando "/", e sem a rota a requisição cairia no painel, que pede login.
@router.api_route("/biopinterest/", methods=["GET", "HEAD"], include_in_schema=False)
@router.api_route("/biopinterest", methods=["GET", "HEAD"], include_in_schema=False)
def bio_page_pinterest(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    """A mesma vitrine, para o campo "Site" do perfil do Pinterest.

    Prefere links do canal `pin`: o clique de quem chega pelo perfil do Pinterest tem de
    entrar como Pinterest, e não como o canal de um link antigo do mesmo produto.
    """
    return _page(db, settings, prefer_channel="pin")
