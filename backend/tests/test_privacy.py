"""Política de privacidade: as afirmações verificáveis do texto precisam continuar verdadeiras."""

import re

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def _with(contact: str):
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, privacy_contact_email=contact
    )


def test_the_page_is_public_html_and_is_indexable(client):
    response = client.get("/privacidade")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    # Ao contrário de /l e /go/, esta página não leva a link de afiliado.
    assert "x-robots-tag" not in response.headers
    assert "noindex" not in response.text.lower()


def test_robots_does_not_block_the_policy(client):
    assert "/privacidade" not in client.get("/robots.txt").text


def test_it_never_shows_the_marketplace_brand(client):
    """Termos 2.3(a): é a página que o app do Pinterest aponta."""
    assert "shopee" not in client.get("/privacidade").text.lower()


def test_the_claims_about_ip_and_cookies_match_the_code(client):
    text = client.get("/privacidade").text
    assert "endereço IP não é gravado" in text and "Não uso cookies" in text
    # E o código de fato não grava IP: a coluna não existe.
    from app.models.tracking import LinkClick

    assert not {c.name for c in LinkClick.__table__.columns} & {"ip", "ip_address", "remote_addr"}


def test_it_sets_no_cookie(client):
    assert "set-cookie" not in client.get("/privacidade").headers


def test_it_describes_what_is_really_stored_from_pinterest_and_the_human_approval(client):
    """Corrigido em 07/11/2026: a versão anterior dizia que só tokens e métricas eram guardados."""
    # O HTML quebra linha no meio das frases: compara com os espaços normalizados.
    text = " ".join(client.get("/privacidade").text.lower().split())
    assert "únicos dados" not in text
    # O que o código de fato guarda do Pinterest: tokens, ids do que o MP cria e analytics
    # de campanha da própria conta (a exceção que a regra 2.2 das Diretrizes permite).
    assert "tokens" in text
    assert "identificadores dos pins, campanhas" in text
    assert "números de campanha da minha conta" in text
    # E a promessa que a fila de aprovação torna verdadeira.
    assert "nada é publicado sem que uma pessoa aprove aquele pin" in text
    assert "criadas pausadas" in text


def test_it_states_the_affiliate_relationship_and_the_pinterest_scope(client):
    text = client.get("/privacidade").text
    assert "sem custo extra" in text
    assert "não acesso, não copio e não armazeno dados de outras pessoas" in text.lower()


def test_it_does_not_promise_a_retention_period_the_code_does_not_keep(client):
    text = client.get("/privacidade").text
    assert "não há um prazo automático" in text
    retention = text.split("Por quanto tempo")[1].split("Seus direitos")[0]
    assert not re.search(r"\d+\s*(dias|meses|anos)", retention)


def test_it_does_not_assume_the_operator_gender(client):
    text = client.get("/privacidade").text
    assert not re.search(r"\beu mesm[ao]\b|\bsou (a|o) responsável", text)


def test_the_contact_email_is_shown_only_when_configured_and_is_escaped(client):
    _with("")
    assert "mailto:" not in client.get("/privacidade").text
    assert "perfil do Pinterest" in client.get("/privacidade").text

    _with('a"><script>x</script>@t.com')
    html = client.get("/privacidade").text
    assert "<script>x</script>" not in html


def test_head_works_for_url_validators(client):
    response = client.head("/privacidade")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_it_names_the_app_the_scopes_and_has_an_english_summary(client):
    """Negação do Trial: a política precisa ligar o app (nome e ID) ao domínio e ser legível."""
    text = " ".join(client.get("/privacidade").text.split())
    assert "MP AUTO" in text and "1634598" in text
    for scope in ("boards:read", "boards:write", "pins:read", "pins:write"):
        assert scope in text
    assert "English summary" in text
    assert "tokens guardados" in text
    assert "shopee" not in text.lower()
