"""Política de privacidade pública, em `/privacidade`.

Existe por dois motivos práticos: o Pinterest exige um link de política de privacidade para
liberar o Standard access, e quem clica num pin tem o direito de saber o que acontece com
o clique. O texto descreve **o que o código faz de fato** — se o comportamento mudar (outro
dado coletado, outro destino), esta página precisa mudar junto, e o teste que a acompanha
trava as afirmações verificáveis (IP, cookies, marca do marketplace).

Duas escolhas de redação:

* Não cita o nome do marketplace. É mídia de afiliado, e os Termos 2.3(a) proíbem marca,
  nome e logo do marketplace nela; a página é o que o app do Pinterest aponta.
* Não promete prazo de retenção. O sistema não apaga clique por idade hoje, e afirmar um
  prazo que o código não cumpre seria o pior erro possível numa política de privacidade.
"""

from html import escape

from fastapi import APIRouter, Depends, Response

from app.core.config import Settings, get_settings

router = APIRouter(tags=["public"])

UPDATED = "12/11/2026"

STYLE = """
:root{color-scheme:light dark;--bg:#fff;--fg:#1c2128;--muted:#59636e;--line:#d1d9e0;--link:#0969da}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;
--line:#30363d;--link:#58a6ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.65 system-ui,-apple-system,
Segoe UI,Roboto,Helvetica,Arial,sans-serif;padding:32px 16px 64px}
main{max-width:720px;margin:0 auto}
h1{font-size:1.7rem;letter-spacing:-.02em;margin:0 0 4px}
h2{font-size:1.1rem;margin:32px 0 6px;padding-top:16px;border-top:1px solid var(--line)}
p,li{margin:8px 0}
ul{padding-left:22px}
.meta{color:var(--muted);font-size:.9rem}
a{color:var(--link)}
"""


def _contact(email: str) -> str:
    if email:
        safe = escape(email)
        return f'Escreva para <a href="mailto:{safe}">{safe}</a>.'
    return "Envie uma mensagem pelo perfil do Pinterest que publica estes conteúdos."


def _contact_en(email: str) -> str:
    if email:
        safe = escape(email)
        return f'<a href="mailto:{safe}">{safe}</a>.'
    return "send a message through the Pinterest profile that publishes this content."


def render(*, title: str, contact_email: str) -> str:
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Política de privacidade · {escape(title)}</title>
<style>{STYLE}</style></head><body><main>
<h1>Política de privacidade</h1>
<p class="meta">{escape(title)} · atualizada em {UPDATED}</p>

<p>Este site reúne indicações de produtos que eu seleciono e divulgo em redes sociais.
Aqui está, em linguagem direta, o que acontece com os seus dados quando você abre um dos
links.</p>
<p>Esta página é também a política de privacidade do aplicativo <strong>MP AUTO</strong>
(Pinterest App ID 1634598), a ferramenta pessoal que uso para preparar os pins desta conta.
<a href="#english">English summary below.</a></p>

<h2>Quem é o responsável</h2>
<p>Este site e os perfis que o divulgam são operados por uma pessoa física, que responde
pelo tratamento descrito abaixo (LGPD, Lei 13.709/2018). Para falar sobre dados pessoais:
{_contact(contact_email)}</p>

<h2>O que eu coleto quando você clica em um link</h2>
<p>Cada link daqui passa por um endereço nosso antes de levar você à loja. Nessa passagem
eu registro:</p>
<ul>
<li>o momento do clique e de qual link e canal (por exemplo, um pin) ele veio;</li>
<li>o navegador e o sistema que você usa (o texto "user-agent" que o navegador envia);</li>
<li>a página de onde você veio, quando o navegador informa;</li>
<li>um código embaralhado, criado a partir do seu endereço de rede, do navegador e da data,
que serve só para contar uma pessoa uma vez por dia.</li>
</ul>
<p><strong>Seu endereço IP não é gravado.</strong> O código embaralhado não permite recuperar
o IP e muda todos os dias, então não serve para acompanhar você de um dia para o outro.</p>
<p><strong>Não uso cookies</strong> nestas páginas, nem pixels de rastreamento, nem
ferramentas de análise de terceiros.</p>

<h2>Para que uso isso</h2>
<ul>
<li>saber quais indicações recebem cliques e quais viram compra, para decidir o que
continuar divulgando;</li>
<li>separar cliques de pessoas dos acessos automáticos (pré-visualizadores de mensagem e
robôs), para não distorcer essa conta.</li>
</ul>
<p>Não vendo dados, não monto perfil de pessoas e não uso essas informações para
publicidade dirigida a você.</p>

<h2>Relação de afiliado</h2>
<p>Os links são de afiliado: se você comprar depois de clicar, posso receber uma comissão da
loja, <strong>sem custo extra para você</strong>. A compra acontece inteiramente no site da
loja, que tem a própria política de privacidade e é quem trata os dados do seu pedido. Eu
não vejo o que você compra nem seus dados de cadastro ou pagamento; recebo apenas um
relatório de vendas atribuídas ao link, sem identificar o comprador.</p>

<h2>Integração com o Pinterest</h2>
<p>O aplicativo MP AUTO é de uso pessoal: só eu o uso, apenas na <strong>minha própria
conta</strong> do Pinterest, para publicar pins e, quando esse recurso estiver autorizado,
criar e acompanhar anúncios. As permissões que ele pede são <code>boards:read</code>,
<code>boards:write</code>, <code>pins:read</code> e <code>pins:write</code>. Em particular:</p>
<ul>
<li><strong>Cada pin é escolhido por uma pessoa.</strong> A ferramenta sugere pins, mas nada
é publicado sem que uma pessoa aprove aquele pin, um a um. Campanhas de anúncio são criadas
pausadas e só começam a rodar quando uma pessoa as ativa manualmente.</li>
<li>leio os <em>meus próprios</em> boards para escolher onde publicar; só o número do board
escolhido fica guardado na configuração;</li>
<li>guardo as credenciais de acesso da minha conta (tokens), de forma protegida no meu
servidor;</li>
<li>guardo os identificadores dos pins, campanhas, grupos de anúncios e anúncios que a
própria ferramenta cria, para saber qual é qual;</li>
<li>dos meus anúncios, guardo os números de campanha da minha conta (impressões, cliques e
gasto por dia), para avaliar o resultado;</li>
<li>não guardo mais nada obtido da API do Pinterest: quando preciso de outra informação,
consulto a API na hora;</li>
<li>não acesso, não copio e não armazeno dados de outras pessoas que usam o Pinterest, como
perfis, listas de seguidores, boards de terceiros ou mensagens;</li>
<li>não compartilho nem vendo dados obtidos do Pinterest.</li>
</ul>
<p>Ao revogar o acesso do aplicativo nas configurações da conta do Pinterest, eu apago os
tokens guardados. Pedidos de eliminação de dados são respondidos em até 15 dias.</p>
<p>O aplicativo segue as Diretrizes de Desenvolvedor do Pinterest: não coleta dados do
Pinterest por scraping, não treina modelos com eles e não os usa para outra finalidade.</p>

<h2>Com quem os dados ficam</h2>
<p>Os registros ficam em servidor sob meu controle. Não os envio a terceiros para publicidade
ou análise. Posso compartilhar apenas se uma autoridade exigir, na forma da lei.</p>

<h2>Por quanto tempo</h2>
<p>Hoje não há um prazo automático de exclusão dos registros de clique; eles são mantidos
enquanto forem úteis para medir o desempenho das indicações. Por serem dados sem o seu IP e
sem seu nome, eles normalmente não identificam você. Se quiser que eu apague algo, peça.</p>

<h2>Seus direitos</h2>
<p>Pela LGPD você pode pedir confirmação de que trato dados seus, acesso, correção,
eliminação, informação sobre compartilhamento e a revogação de consentimento, quando for o
caso. Como não guardo seu IP nem seu nome, talvez eu precise de informações adicionais, como
o link que você abriu e o dia, para localizar um registro. {_contact(contact_email)}</p>

<h2>Crianças</h2>
<p>Este site não é dirigido a menores de 13 anos e eu não coleto dados de crianças de
propósito.</p>

<h2>Mudanças</h2>
<p>Se eu mudar o que coleto ou como uso, atualizo esta página e a data no topo.</p>

<h2 id="english">English summary</h2>
<p>This page is the privacy policy of <strong>MP AUTO</strong> (Pinterest App ID 1634598), a
private single-user tool used by the owner of this Pinterest business account to manage their
own affiliate content. It requests the scopes <code>boards:read</code>,
<code>boards:write</code>, <code>pins:read</code> and <code>pins:write</code>, and only
accesses the owner's own boards and pins.</p>
<ul>
<li><strong>Every pin is approved individually by a person</strong> before it is published;
nothing is posted automatically.</li>
<li>Pinterest data stored: OAuth tokens, the IDs of the pins/campaigns the tool itself
creates, and campaign analytics of the owner's own account. Nothing else obtained from the
Pinterest API is stored; data of other Pinterest users is never accessed or stored.</li>
<li>Pinterest data is not sold, shared, scraped, or used to train models.</li>
<li>When access is revoked in the Pinterest account settings, the stored tokens are deleted.
Deletion requests are answered within 15 days.</li>
<li>Visitors who click a link: the click time, link/channel, browser string, referrer and a
daily-rotating hash are recorded; the IP address is not stored and no cookies, tracking
pixels or third-party analytics are used.</li>
<li>Links are affiliate links; the site owner may earn a commission at no extra cost to the
buyer.</li>
</ul>
<p>Contact: {_contact_en(contact_email)}</p>
</main></body></html>"""


# HEAD além de GET: validadores de URL (inclusive o formulário do Pinterest) costumam
# conferir o link com HEAD, e um 405 ali parece página inexistente.
@router.api_route("/privacidade", methods=["GET", "HEAD"], include_in_schema=False)
def privacy_page(settings: Settings = Depends(get_settings)) -> Response:
    # Sem NO_INDEX de propósito: ao contrário de /l e /go/, esta página não leva a link de
    # afiliado e precisa ser acessível a quem avalia o app e a quem clica.
    html = render(title=settings.bio_page_title, contact_email=settings.privacy_contact_email)
    return Response(content=html, media_type="text/html; charset=utf-8")
