#!/usr/bin/env python3
"""Gera os workflows do n8n a partir de uma descrição curta.

O n8n NÃO tem regra de negócio aqui: só agenda, encadeia, faz retry e notifica. Toda a
lógica vive no FastAPI, onde é testável. Reexecute este script depois de mudar algo e
commite os .json gerados.

    python3 n8n/generate.py
"""

import json
import uuid
from pathlib import Path

OUT = Path(__file__).parent / "workflows"
BACKEND = "http://mp-backend:8000/api/v1"

# IDs fixos: o credential e o workflow de erro precisam ter o MESMO id em qualquer
# instalação, senão os workflows importados não os encontram.
CRED_ID = "mpApiKey00000001"
CRED_NAME = "MP API Key"
ERROR_WORKFLOW_ID = "mpErrorHandler001"
NOTIFY_PLACEHOLDER = "https://CONFIGURE-O-WEBHOOK-DE-NOTIFICACAO.invalid/"


def _id(*parts: str) -> str:
    """UUID determinístico: reexecutar o gerador não muda o diff à toa."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "mp/" + "/".join(parts)))


def schedule(name: str, rule: dict) -> dict:
    return {
        "parameters": {"rule": {"interval": [rule]}},
        "name": name,
        "type": "n8n-nodes-base.scheduleTrigger",
        "typeVersion": 1.2,
    }


def every_hours(hours: int) -> dict:
    return {"field": "hours", "hoursInterval": hours}


def daily_at(hour: int, minute: int = 0) -> dict:
    return {"field": "days", "daysInterval": 1, "triggerAtHour": hour, "triggerAtMinute": minute}


def call(
    name: str, path: str, step: str, *, keep_going: bool = False, json_body: dict | None = None
) -> dict:
    """POST autenticado no backend, com Idempotency-Key e retry.

    A chave é a mesma em todas as tentativas de UMA execução (o retry reenvia o mesmo
    valor), então um retry depois de resposta perdida devolve o resultado guardado em
    vez de repetir o efeito. Cada execução nova gera chave nova.
    """
    node = {
        "parameters": {
            "method": "POST",
            "url": f"{BACKEND}/{path}",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {
                        "name": "Idempotency-Key",
                        "value": "={{ $workflow.id }}-{{ $execution.id }}-" + step,
                    }
                ]
            },
            "options": {"timeout": 180000},
        },
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "credentials": {"httpHeaderAuth": {"id": CRED_ID, "name": CRED_NAME}},
        "retryOnFail": True,
        "maxTries": 3,
        "waitBetweenTries": 5000,
    }
    if json_body is not None:
        node["parameters"].update(
            {"sendBody": True, "specifyBody": "json", "jsonBody": json.dumps(json_body)}
        )
    if keep_going:
        # Falhou depois das tentativas? Segue mesmo assim: o resumo do dia sai de qualquer jeito
        # (e avisa que o dado está velho), em vez de o dono ficar sem notícia.
        node["onError"] = "continueRegularOutput"
    return node


def condition(name: str, left: str, op_type: str, operation: str, right) -> dict:
    return {
        "parameters": {
            "conditions": {
                "options": {
                    "caseSensitive": True,
                    "leftValue": "",
                    "typeValidation": "strict",
                    "version": 2,
                },
                "conditions": [
                    {
                        "id": _id("cond", name),
                        "leftValue": left,
                        "rightValue": right,
                        "operator": {"type": op_type, "operation": operation},
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
        "name": name,
        "type": "n8n-nodes-base.if",
        "typeVersion": 2.2,
    }


def notify(name: str, text_expression: str) -> dict:
    """Webhook genérico. O corpo leva `text` (Slack/Mattermost) e `content` (Discord)."""
    body = "={{ JSON.stringify({ text: " + text_expression + ", content: " + text_expression + " }) }}"
    return {
        "parameters": {
            "method": "POST",
            "url": NOTIFY_PLACEHOLDER,
            "sendBody": True,
            "specifyBody": "json",
            "jsonBody": body,
            "options": {"timeout": 15000},
        },
        "name": name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "retryOnFail": True,
        "maxTries": 3,
        "waitBetweenTries": 3000,
    }


def build(name: str, workflow_id: str, nodes: list[dict], links: list[tuple], *, error_handler=True) -> dict:
    """Posiciona os nós em linha e monta as conexões (origem, destino[, saída])."""
    positioned = []
    for i, node in enumerate(nodes):
        node = dict(node)
        node["id"] = _id(workflow_id, node["name"])
        node["position"] = [260 * i, 300]
        positioned.append(node)

    connections: dict = {}
    for link in links:
        source, target = link[0], link[1]
        output = link[2] if len(link) > 2 else 0
        slots = connections.setdefault(source, {"main": []})["main"]
        while len(slots) <= output:
            slots.append([])
        slots[output].append({"node": target, "type": "main", "index": 0})

    settings = {"executionOrder": "v1", "timezone": "America/Sao_Paulo"}
    if error_handler:
        settings["errorWorkflow"] = ERROR_WORKFLOW_ID
    return {
        "id": workflow_id,
        "name": name,
        "active": False,
        "nodes": positioned,
        "connections": connections,
        "settings": settings,
        "pinData": {},
        "meta": {"templateCredsSetupCompleted": True},
    }


def chain(*names: str) -> list[tuple]:
    return [(a, b) for a, b in zip(names, names[1:], strict=False)]


WORKFLOWS: dict[str, dict] = {}

# 00 — recebe a falha de QUALQUER outro workflow (configurado em settings.errorWorkflow).
WORKFLOWS["00_error_handler"] = build(
    "MP 00 · Erro em workflow",
    ERROR_WORKFLOW_ID,
    [
        {"parameters": {}, "name": "Falha", "type": "n8n-nodes-base.errorTrigger", "typeVersion": 1},
        notify(
            "Notificar",
            "'🔴 MP: falha no workflow \"' + $json.workflow.name + '\" (execução ' + $json.execution.id + ')\\n"
            "Nó: ' + ($json.execution.lastNodeExecuted || '?') + '\\n"
            "Erro: ' + ($json.execution.error ? $json.execution.error.message : '?')",
        ),
    ],
    chain("Falha", "Notificar"),
    error_handler=False,  # o próprio handler não pode se auto-notificar em loop
)

WORKFLOWS["01_discovery"] = build(
    "MP 01 · Descoberta e qualificação",
    "mpWorkflow01Disc",
    [
        schedule("Diário 03:00", daily_at(3)),
        # Duas varreduras, porque procuram coisas diferentes (docs/plano-10k.md §2).
        # Por VENDAS: 25 categorias × 40 = ~1000 produtos, demanda provada e comissão
        # baixa (mediana medida: R$ 3 por venda).
        call(
            "Descobrir mais vendidos",
            "trigger/discovery",
            "discovery",
            json_body={"by_category": True, "per_category": 40},
        ),
        # Por PREÇO DECRESCENTE: alcança a cauda de comissão alta, que a ordenação por
        # vendas nunca mostra, e guarda só o que também TEM venda. ~625 chamadas.
        call(
            "Varrer comissão alta",
            "trigger/discovery",
            "discovery",
            json_body={"by_commission": True},
        ),
        call("Qualificar", "trigger/qualification", "qualification"),
        call("Pontuar oportunidade", "trigger/scoring/opportunity", "scoring"),
        # Receita esperada por clique: precisa do snapshot novo, então vem depois das
        # varreduras. A evidência de clique entra de novo no workflow 06.
        call("Calcular receita esperada", "trigger/scoring/ev", "ev"),
    ],
    chain(
        "Diário 03:00",
        "Descobrir mais vendidos",
        "Varrer comissão alta",
        "Qualificar",
        "Pontuar oportunidade",
        "Calcular receita esperada",
    ),
)

WORKFLOWS["02_portfolio_manager"] = build(
    "MP 02 · Promover candidatos",
    "mpWorkflow02Port",
    [
        schedule("Diário 05:00", daily_at(5)),
        call("Promover a CANDIDATE", "trigger/candidates/promote", "promote"),
    ],
    chain("Diário 05:00", "Promover a CANDIDATE"),
)

WORKFLOWS["03_affiliate_links"] = build(
    "MP 03 · Links de afiliado",
    "mpWorkflow03Link",
    [
        schedule("Diário 06:00", daily_at(6)),
        call("Gerar links", "trigger/links/generate", "links"),
    ],
    chain("Diário 06:00", "Gerar links"),
)

WORKFLOWS["05_meta_ads_creation"] = build(
    "MP 05 · Criar campanhas (PAUSED)",
    "mpWorkflow05Ads0",
    [
        schedule("Diário 06:30", daily_at(6, 30)),
        call("Criar campanhas PAUSED", "trigger/ads/create", "ads"),
        condition("Abortou?", "={{ $json.status }}", "string", "equals", "ABORTED"),
        notify(
            "Notificar aborto",
            "'🟠 MP: a criação de campanhas ABORTOU. ' + ($json.warnings || []).join(' | ')",
        ),
    ],
    chain("Diário 06:30", "Criar campanhas PAUSED", "Abortou?") + [("Abortou?", "Notificar aborto", 0)],
)

WORKFLOWS["06_performance_sync"] = build(
    "MP 06 · Sincronizar performance",
    "mpWorkflow06Perf",
    [
        schedule("A cada 4h", every_hours(4)),
        call("Sincronizar Insights e conversões", "trigger/performance/sync", "sync"),
        call("Consolidar e pontuar", "trigger/performance/consolidate", "consolidate"),
        # Clique e venda recém-consolidados viram evidência da posterior: aqui o EV deixa
        # de ser prior e passa a ser medição (docs/plano-10k.md §3.2).
        call("Recalcular receita esperada", "trigger/scoring/ev", "ev"),
        call("Fotografar portfólio", "trigger/portfolio/snapshot", "snapshot"),
    ],
    chain(
        "A cada 4h",
        "Sincronizar Insights e conversões",
        "Consolidar e pontuar",
        "Recalcular receita esperada",
        "Fotografar portfólio",
    ),
)

WORKFLOWS["07_ai_decision_cycle"] = build(
    "MP 07 · Ciclo de decisão da IA",
    "mpWorkflow07Deci",
    [
        schedule("Diário 05:30", daily_at(5, 30)),
        call("Analisar portfólio (RECOMMEND)", "portfolio/analyze", "analyze"),
        call("Aplicar o que a autonomia permite", "portfolio/apply", "apply"),
    ],
    chain("Diário 05:30", "Analisar portfólio (RECOMMEND)", "Aplicar o que a autonomia permite"),
)

WORKFLOWS["04_content_package"] = build(
    "MP 04 · Pacote de conteúdo e publicação",
    "mpWorkflow04Cont",
    [
        schedule("Diário 06:00", daily_at(6)),
        call("Gerar pacote de conteúdo", "trigger/content/generate", "content"),
        {
            "parameters": {"fieldToSplitOut": "items", "options": {}},
            "name": "Um post por mensagem",
            "type": "n8n-nodes-base.splitOut",
            "typeVersion": 1,
        },
        notify("Notificar pacote", "$json.caption"),
        # Publicação é RAMO PARALELO, não elo da cadeia: "Um post por mensagem" divide a
        # resposta em N itens, e qualquer nó depois dele rodaria N vezes — ou seja,
        # publicaria o lote uma vez por produto.
        #
        # A publicação só leva ao ar o que uma PESSOA aprovou no painel (Diretrizes do
        # Pinterest, 4.3). Às 06:00 isto quase sempre publica zero e serve para AVISAR
        # quantos pins aguardam decisão; quem publica depois da aprovação é o workflow 04b.
        #
        # keep_going: se o Pinterest cair, as legendas já saíram no outro ramo e a
        # notificação abaixo conta o que houve. Melhor isso que o workflow inteiro
        # falhar e o dono não receber nada.
        call("Publicar na rede social", "trigger/content/publish", "publish", keep_going=True),
        notify(
            "Notificar publicação",
            "($json.status === 'SKIPPED'"
            " ? '⏸️ MP: a publicação não rodou — ' + ($json.warnings || []).join(' ')"
            " : '📌 MP: ' + ($json.summary.awaiting_approval || 0) + ' pin(s) aguardando a sua aprovação'"
            " + ($json.summary.queue_url ? ' → ' + $json.summary.queue_url : '')"
            " + ' · ' + ($json.summary.published || 0) + ' publicado(s), '"
            " + ($json.summary.dry_run || 0) + ' em ensaio, '"
            " + ($json.summary.blocked || 0) + ' barrado(s) por risco de marca, '"
            " + ($json.summary.failed || 0) + ' com falha'"
            " + ' [' + ($json.summary.network || '?') + ']')",
        ),
    ],
    chain("Diário 06:00", "Gerar pacote de conteúdo", "Um post por mensagem", "Notificar pacote")
    + chain("Gerar pacote de conteúdo", "Publicar na rede social", "Notificar publicação"),
)

# Publica o que a pessoa aprovou. De hora em hora, e sem avisar quando nada saiu: uma
# aprovação feita às 14h42 sai às 15h, e o dono só ouve falar disso se algo de fato foi ao ar
# ou falhou. keep_going: uma queda do Pinterest não deve virar execução com erro a cada hora.
WORKFLOWS["04b_publish_approved"] = build(
    "MP 04b · Publicar pins aprovados",
    "mpWorkflow04bPub",
    [
        schedule("A cada 1h", every_hours(1)),
        call("Publicar o que foi aprovado", "trigger/content/publish", "publish", keep_going=True),
        condition(
            "Saiu ou falhou algo?",
            "={{ (($json.summary && $json.summary.published) || 0)"
            " + (($json.summary && $json.summary.failed) || 0) }}",
            "number",
            "gt",
            0,
        ),
        notify(
            "Notificar publicação aprovada",
            "'📌 MP: ' + ($json.summary.published || 0) + ' pin(s) publicado(s)'"
            " + ($json.summary.failed ? ', ' + $json.summary.failed + ' com falha' : '')"
            " + ($json.warnings && $json.warnings.length ? ' — ' + $json.warnings.join(' ') : '')",
        ),
    ],
    chain("A cada 1h", "Publicar o que foi aprovado", "Saiu ou falhou algo?")
    + [("Saiu ou falhou algo?", "Notificar publicação aprovada", 0)],
)

WORKFLOWS["09_daily_report"] = build(
    "MP 09 · Resumo do dia (WhatsApp)",
    "mpWorkflow09Repo",
    [
        schedule("Diário 21:00", daily_at(21)),
        call("Sincronizar vendas", "trigger/performance/sync", "sync", keep_going=True),
        call("Consolidar", "trigger/performance/consolidate", "consolidate", keep_going=True),
        call("Montar resumo", "trigger/report/daily", "report"),
        notify("Notificar resumo", "$json.summary.message"),
    ],
    chain("Diário 21:00", "Sincronizar vendas", "Consolidar", "Montar resumo", "Notificar resumo"),
)

WORKFLOWS["08_alerts_monitor"] = build(
    "MP 08 · Monitor de alertas",
    "mpWorkflow08Aler",
    [
        schedule("A cada 1h", every_hours(1)),
        call("Avaliar alertas", "trigger/alerts/evaluate", "alerts"),
        condition("Há alerta novo?", "={{ $json.summary.created }}", "number", "gt", 0),
        notify(
            "Notificar alertas",
            "'🔔 MP: ' + $json.items.map(i => '[' + i.severity + '] ' + i.message).join('\\n')",
        ),
    ],
    chain("A cada 1h", "Avaliar alertas", "Há alerta novo?") + [("Há alerta novo?", "Notificar alertas", 0)],
)

CREDENTIAL = [
    {
        "id": CRED_ID,
        "name": CRED_NAME,
        "type": "httpHeaderAuth",
        "data": {"name": "X-API-Key", "value": "__N8N_API_KEY__"},
    }
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.json"):
        stale.unlink()
    for filename, workflow in WORKFLOWS.items():
        (OUT / f"{filename}.json").write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n")
    (OUT.parent / "credential.template.json").write_text(json.dumps(CREDENTIAL, indent=2) + "\n")
    print(f"{len(WORKFLOWS)} workflows + credential.template.json em {OUT.parent}")


if __name__ == "__main__":
    main()
