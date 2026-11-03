"""Contrato de publicação orgânica em rede social. Uma rede, um adaptador.

Por que isto não entrou em `adapters/ads`: lá se cria campanha paga, com orçamento,
segmentação e um gateway que precisa de guarda de verba. Aqui é post orgânico — não há
dinheiro no caminho, o limite de taxa é de outra ordem de grandeza e o modo de falha é
outro (post recusado por conteúdo, não campanha estourando budget).

Cada rede declara os seus próprios limites de campo em `limits`. Quem monta o texto
pergunta ao adaptador em vez de carregar número de rede nenhuma no serviço: 100
caracteres de título é fato do Pinterest, não regra do MP.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class SocialError(Exception):
    """Falha na publicação."""


class SocialAuthError(SocialError):
    """Credencial inválida ou expirada. Configuração — repetir não conserta."""


class SocialRateLimited(SocialError):
    """Limite de taxa depois de esgotar as tentativas."""


class SocialRejected(SocialError):
    """A rede recusou o conteúdo (4xx que não é limite nem credencial)."""


@dataclass(frozen=True)
class PostLimits:
    """Limites de campo da rede, em caracteres."""

    title: int
    description: int
    alt_text: int
    link: int
    # Quantos posts a rede/plano aceita por dia. None = sem limite conhecido.
    per_day: int | None = None


@dataclass(frozen=True)
class PostDraft:
    title: str
    description: str
    link: str
    image_url: str
    alt_text: str | None = None

    def problems(self, limits: PostLimits) -> tuple[str, ...]:
        """O que impede este rascunho de ser publicado. Vazio = pode ir.

        Só checa o que a rede recusaria; truncar texto comprido é trabalho de `fit`,
        não motivo para abortar.
        """
        failed: list[str] = []
        if not self.title.strip():
            failed.append("sem título")
        if not self.image_url.strip():
            failed.append("sem imagem")
        if not self.link.strip():
            failed.append("sem link")
        elif len(self.link) > limits.link:
            # Link não se trunca: URL cortada é link quebrado.
            failed.append(f"link com {len(self.link)} caracteres (máx {limits.link})")
        return tuple(failed)


@dataclass(frozen=True)
class PublishedPost:
    external_post_id: str
    url: str | None
    raw: dict


def fit(text: str, limit: int) -> str:
    """Corta em fronteira de palavra, com reticência. Nunca estoura o limite.

    Cortar no meio da palavra é o que todo truncamento ingênuo faz e fica visível no
    post. A reticência entra dentro do orçamento, não além dele.
    """
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    hard = text[: limit - 1]
    # Se o próximo caractere do original é espaço, o corte JÁ caiu em fronteira de palavra
    # e recuar só jogaria texto fora de graça.
    if len(text) > len(hard) and text[len(hard)] != " ":
        space = hard.rfind(" ")
        # Recua, a menos que isso custe mais da metade do orçamento — o que só acontece
        # quando uma palavra sozinha é maior que o limite (URL colada, código de produto).
        # Aí o corte duro é o menos ruim.
        if space > limit * 0.5:
            hard = hard[:space]
    return hard.rstrip(" ,.;:-") + "…"


class SocialAdapter(ABC):
    code: str
    display_name: str

    @property
    @abstractmethod
    def limits(self) -> PostLimits: ...

    @abstractmethod
    def publish(self, draft: PostDraft) -> PublishedPost:
        """Publica e devolve o id da rede. Levanta SocialError em qualquer falha."""
