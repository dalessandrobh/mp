# Affiliate Intelligence & Automation Platform

Plataforma que gerencia de forma autônoma um portfólio de produtos de afiliado
(Shopee, Amazon, Mercado Livre), do descobrimento à decisão de investimento.

- `ARCHITECTURE.md` — especificação (fonte da verdade)
- `PLANNING.md` — plano técnico, schema e roadmap
- `VALIDATION_STATUS.md` — status de validação das APIs externas
- `docs/shopee_api_schema_reference.md` — referência completa da API Shopee

## Trilhos de segurança

Três invariantes garantidos por código **e** por schema:

1. Nada muda o estado de um produto fora de `domain/state_machine.py`.
2. Nada cria estrutura no Meta fora de `services/ads_gateway.py`.
3. Nada aloca orçamento fora de `services/budget_guard.py`.

Campanhas são **sempre** criadas com status `PAUSED` — a ativação é manual no
Gerenciador do Meta. A constraint `campaigns_must_be_created_paused` grava essa
regra no banco, não apenas na aplicação.

## Rodando local

```bash
cp .env.example .env          # ajuste o que precisar
docker compose up -d postgres
cd backend
pip install -e ".[dev]"
alembic upgrade head          # cria o schema + seeds de parâmetros
uvicorn app.main:app --reload
```

API em `http://localhost:8000`, docs em `/docs`, health em `/api/v1/health`.

Com `MOCK_MARKETPLACE=true` e `MOCK_ADS=true` (default) nenhum sistema externo
é tocado — a plataforma roda inteira contra adapters de mock.

## Testes

```bash
cd backend
pytest
ruff check .
```

## Deploy na VPS

`deploy/RUNBOOK.md` cobre o cenário de uma VPS que já roda n8n e Supabase
self-hosted: o backend sobe ao lado deles, sem tocar em portas 80/443 nem no
proxy reverso existente.

As tabelas ficam num banco `mp` dedicado, e não no banco `postgres` do
Supabase — assim o PostgREST não tem como publicá-las, já que ele só enxerga o
banco ao qual se conecta.
