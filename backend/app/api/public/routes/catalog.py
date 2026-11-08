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

# Paleta em laranja, inspirada nas cores da Shopee. SÓ AS CORES: nada de logo, nome, fonte,
# selo ("Mall", "Frete grátis") ou desenho de interface do marketplace. A página vende o
# produto de outra pessoa; se parecesse a loja oficial, enganaria quem chega (Termos da
# Shopee 2.3(a) e 4.3(j)) — por isso o layout é próprio e o aviso de afiliado fica visível.
#
# Tampouco imita o Pinterest: nada de mosaico de alturas diferentes nem o vermelho dele
# (Diretrizes de Desenvolvedor 4.7: "replicating or imitating the visual design, layout, or
# user experience of Pinterest").
#
# O laranja puro (#EE4D2D) com texto branco dá 3,66:1, abaixo dos 4,5:1 de legibilidade. Por
# isso ele fica nos detalhes (faixa, bordas, foco) e o botão e o preço usam `strong`.
PALETTE = {
    "light": {
        "bg": "#F5F5F5",
        "card": "#FFFFFF",
        "ink": "#222222",
        "muted": "#666666",
        "tint": "#FFF3EE",
        "line": "#EBDDD6",
        "orange": "#EE4D2D",
        "amber": "#F69113",
        "strong": "#C93012",
        "on_strong": "#FFFFFF",
    },
    "dark": {
        "bg": "#1B1512",
        "card": "#261D19",
        "ink": "#F5EDE9",
        "muted": "#B9A9A2",
        "tint": "#2E211B",
        "line": "#3A2B24",
        "orange": "#FF7A59",
        "amber": "#F69113",
        "strong": "#FF7A59",
        "on_strong": "#1B1512",
    },
}


def _vars(theme: dict[str, str]) -> str:
    return "".join(f"--{key.replace('_', '-')}:{value};" for key, value in theme.items())


STYLE = (
    f":root{{color-scheme:light dark;{_vars(PALETTE['light'])}}}"
    f"@media(prefers-color-scheme:dark){{:root{{{_vars(PALETTE['dark'])}}}}}"
    + """
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",
Roboto,Helvetica,Arial,sans-serif}
body::before{content:"";display:block;height:6px;
background:linear-gradient(90deg,var(--orange),var(--amber))}
.wrap{max-width:960px;margin:0 auto;padding:28px 16px 48px}
header{text-align:center;margin-bottom:20px}
h1{font-size:1.7rem;line-height:1.2;letter-spacing:-.02em}
.sub{color:var(--muted);font-size:1rem;margin-top:8px}
.note{background:var(--tint);border:1px solid var(--line);border-left:4px solid var(--orange);
border-radius:10px;color:var(--ink);font-size:.85rem;padding:12px 14px;margin:0 auto 24px;
max-width:640px}
ul{list-style:none;display:grid;gap:16px;grid-template-columns:1fr}
@media(min-width:600px){ul{grid-template-columns:repeat(2,1fr)}}
@media(min-width:900px){ul{grid-template-columns:repeat(3,1fr)}}
li{display:flex}
a.card{display:flex;flex-direction:column;width:100%;background:var(--card);
border:1px solid var(--line);border-radius:14px;overflow:hidden;text-decoration:none;
color:inherit;transition:border-color .15s,box-shadow .15s}
a.card:hover{border-color:var(--orange);box-shadow:0 4px 14px rgba(238,77,45,.16)}
a.card:focus-visible{outline:3px solid var(--orange);outline-offset:2px}
img{display:block;width:100%;aspect-ratio:1/1;object-fit:cover;background:var(--tint)}
.info{display:flex;flex-direction:column;flex:1;gap:8px;padding:14px}
.title{font-size:.95rem;font-weight:500;display:-webkit-box;-webkit-line-clamp:2;
-webkit-box-orient:vertical;overflow:hidden;min-height:2.85em}
.price{color:var(--strong);font-size:1.2rem;font-weight:700}
.cta{margin-top:auto;background:var(--strong);color:var(--on-strong);text-align:center;
font-weight:600;font-size:.9rem;padding:10px 12px;border-radius:10px}
.empty{color:var(--muted);text-align:center;padding:48px 0}
footer{color:var(--muted);font-size:.78rem;text-align:center;margin-top:32px}
"""
)


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
        f'{_price(item)}<span class="cta">Ver oferta →</span></div></a></li>'
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
        f"<header><h1>{escape(title)}</h1><p class=\"sub\">{escape(subtitle)}</p></header>"
        f'<p class="note">{escape(DISCLOSURE)}</p>{body}'
        "<footer>Preços e disponibilidade mudam sem aviso; confira na página do produto."
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
