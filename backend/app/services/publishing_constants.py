"""Constantes compartilhadas entre a publicação e a fila de aprovação.

Num módulo à parte para que `approval_service` e `publishing_service` não se importem
um ao outro: a fila precisa conhecer os status de `social_posts`, e a publicação precisa
consultar as decisões da fila.
"""

# Canal do pin orgânico. É explícito (e não `adapter.code`) porque `mock_social` tem
# underline, que o sub_id recusa; ver publishing_service.
CHANNEL = "pin"

# Canal do pin promovido (Pinterest Ads). Link próprio, para a venda do anúncio não cair
# em "pin orgânico" e o gasto poder ser comparado com a receita.
ADS_CHANNEL = "pinads"

STATUS_PUBLISHED = "PUBLISHED"
STATUS_DRY_RUN = "DRY_RUN"
STATUS_BLOCKED = "BLOCKED"
STATUS_FAILED = "FAILED"

DECISION_APPROVED = "APPROVED"
DECISION_REJECTED = "REJECTED"
DECISIONS = (DECISION_APPROVED, DECISION_REJECTED)

# Quantos dias de criativos ficam na fila (hoje e os anteriores). Sem isso, o pacote das
# 06:00 aprovado só no dia seguinte nunca sairia; e sem limite, a fila viraria um depósito.
WINDOW_DAYS = 3
