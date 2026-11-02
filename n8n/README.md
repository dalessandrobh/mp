# Workflows do n8n

Sete workflows de negócio + um tratador de erro. O n8n **só agenda, encadeia, faz retry e
notifica**: nenhuma regra mora aqui. Os arquivos em `workflows/` são **gerados** por
`generate.py` — mude lá e rode `python3 n8n/generate.py`, não edite os `.json` à mão.

| Arquivo | Quando | Chamadas (`http://mp-backend:8000/api/v1/…`) |
|---|---|---|
| `00_error_handler` | falha em qualquer workflow | notifica no webhook |
| `01_discovery` | a cada 6h | `trigger/discovery` → `trigger/qualification` → `trigger/scoring/opportunity` |
| `02_portfolio_manager` | 05:00 | `trigger/candidates/promote` |
| `07_ai_decision_cycle` | 05:30 | `portfolio/analyze` → `portfolio/apply` |
| `03_affiliate_links` | 06:00 | `trigger/links/generate` |
| `05_meta_ads_creation` | 06:30 | `trigger/ads/create` (notifica se `ABORTED`) |
| `06_performance_sync` | a cada 4h | `trigger/performance/sync` → `…/consolidate` → `trigger/portfolio/snapshot` |
| `08_alerts_monitor` | a cada 1h | `trigger/alerts/evaluate` (notifica só se há alerta novo) |

Não há `04_content_generation`: o endpoint ainda não existe (veja `docs/runbook.md` §8).

## Instalar

```bash
bash n8n/install.sh --notify-url "https://seu-webhook" --dry-run   # confere tudo, não importa
bash n8n/install.sh --notify-url "https://seu-webhook"             # importa, INATIVOS
# depois, no editor do n8n: ligue o botão "Active" de cada workflow "MP …"
```

**Não reinicie um n8n que já atende outras automações.** Ativar pelo botão vale na hora.
`--activate` publica pela CLI, mas aí os agendamentos só entram em vigor depois de
`docker restart`, que derruba *todos* os workflows do n8n por alguns segundos — e um webhook
(por exemplo, do WhatsApp) que chegar nesse intervalo pode se perder.

O script cria a credencial **MP API Key** (header `X-API-Key`, valor = `N8N_API_KEY` de
`deploy/.env.prod`) e importa os workflows com IDs fixos: rodar de novo **atualiza** os do
MP sem tocar nos seus. Sem `--activate` eles entram **inativos** (inclusive os que já
estivessem ativos).

`--notify-url` aceita qualquer webhook que receba `POST` JSON: o corpo leva `text`
(Slack, Mattermost) e `content` (Discord). Para outro serviço, edite os nós "Notificar".

## Por trás das escolhas

- **Idempotency-Key** = `workflow-id + execution-id + etapa`. O retry de um nó reenvia a
  mesma chave (não repete o efeito); uma execução nova gera chave nova.
- **Sem `dry_run` na URL:** os workflows herdam o `DRY_RUN` do backend, que é o único
  interruptor. Com `DRY_RUN=true` eles rodam e **nada é gravado**.
- **Credencial, não variável:** o n8n 2.x bloqueia `$env` nas expressões por padrão e
  variáveis do n8n são recurso pago. A chave mora numa credencial.
- Validado contra o **n8n 2.37.4** num container descartável: os 8 workflows importam, a
  cadeia completa executa contra o backend (campanhas só `PAUSED`), `ABORTED` e alertas
  novos notificam, e backend fora do ar falha depois de 3 tentativas.
