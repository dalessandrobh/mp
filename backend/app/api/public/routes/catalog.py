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

STYLE = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0b0f14;color:#e6edf3;font:16px/1.5 system-ui,-apple-system,Segoe UI,
Roboto,Helvetica,Arial,sans-serif;padding:24px 16px 48px}
.wrap{max-width:560px;margin:0 auto}
header{text-align:center;margin-bottom:8px}
h1{font-size:1.5rem;letter-spacing:-.02em}
.sub{color:#8b98a5;font-size:.95rem;margin-top:6px}
.note{background:#121922;border:1px solid #1f2b38;border-radius:12px;color:#8b98a5;
font-size:.8rem;padding:12px 14px;margin:20px 0}
ul{list-style:none;display:flex;flex-direction:column;gap:14px}
li{background:#121922;border:1px solid #1f2b38;border-radius:16px;overflow:hidden}
a.card{display:flex;gap:14px;padding:12px;text-decoration:none;color:inherit;
align-items:center}
a.card:hover{background:#17202b}
img{width:82px;height:82px;object-fit:cover;border-radius:12px;background:#1f2b38;
flex:0 0 auto}
.info{min-width:0;flex:1}
.title{font-size:.94rem;font-weight:500;display:-webkit-box;-webkit-line-clamp:2;
-webkit-box-orient:vertical;overflow:hidden}
.price{color:#4ade80;font-weight:600;margin-top:6px}
.cta{color:#60a5fa;font-size:.82rem;margin-top:4px}
.empty{color:#8b98a5;text-align:center;padding:40px 0}
footer{color:#5b6673;font-size:.72rem;text-align:center;margin-top:28px}
@media(prefers-color-scheme:light){
body{background:#f6f8fa;color:#1f2328}
.note,li{background:#fff;border-color:#d8dee4}
a.card:hover{background:#f0f3f6}
.sub,.note,.empty{color:#656d76}
.price{color:#1a7f37}
}
"""


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
        f'{_price(item)}<div class="cta">Ver oferta →</div></div></a></li>'
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
        f"<title>{escape(title)}</title><style>{STYLE}</style></head><body><div class=\"wrap\">"
        f"<header><h1>{escape(title)}</h1><p class=\"sub\">{escape(subtitle)}</p></header>"
        f'<p class="note">{escape(DISCLOSURE)}</p>{body}'
        "<footer>Preços e disponibilidade mudam sem aviso; confira na página do produto."
        "</footer></div></body></html>"
    )


@router.get("/l", include_in_schema=False)
def bio_page(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    html = render(
        bio_service.bio_items(db),
        title=settings.bio_page_title,
        subtitle=settings.bio_page_subtitle,
    )
    return Response(content=html, media_type="text/html; charset=utf-8", headers=NO_INDEX)
