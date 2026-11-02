#!/usr/bin/env python3
"""Prepara os workflows para uma instalação: aponta as notificações para o canal escolhido.

Os .json versionados trazem um webhook genérico (corpo com `text` e `content`) num endereço
de mentira. Aqui ele vira:

  --notify-url URL       o seu webhook (Slack, Discord, Mattermost…)
  --whatsapp-to NUMERO   mensagem de WhatsApp pela Evolution API
                         (precisa de --evolution-url e --evolution-instance)

O segredo da Evolution NÃO passa por aqui: vive numa credencial do n8n.
"""

import argparse
import json
import re
from pathlib import Path

PLACEHOLDER = "https://CONFIGURE-O-WEBHOOK-DE-NOTIFICACAO.invalid/"
EVOLUTION_CRED_ID = "mpEvolution0000001"
EVOLUTION_CRED_NAME = "MP Evolution API Key"

# O gerador escreve `JSON.stringify({ text: EXPR, content: EXPR })`: a mesma expressão duas vezes.
_BODY = re.compile(r"^=\{\{ JSON\.stringify\(\{ text: (?P<expr>.*), content: (?P=expr) \}\) \}\}$", re.S)


def is_notify_node(node: dict) -> bool:
    return node.get("type") == "n8n-nodes-base.httpRequest" and node["name"].startswith("Notificar")


def to_whatsapp(node: dict, *, evolution_url: str, instance: str, number: str) -> None:
    """Reescreve o nó para `POST {url}/message/sendText/{instance}` (Evolution API v2)."""
    match = _BODY.match(node["parameters"]["jsonBody"])
    if match is None:
        raise SystemExit(f"Corpo inesperado no nó '{node['name']}': o gerador mudou?")
    expr = match["expr"]
    if node["name"].startswith("Notificar pacote"):
        # Post do dia: a foto do produto com a legenda pronta (Evolution `sendMedia`).
        node["parameters"].update(
            {
                "url": f"{evolution_url.rstrip('/')}/message/sendMedia/{instance}",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpHeaderAuth",
                "jsonBody": "={{ JSON.stringify({ number: " + json.dumps(number)
                + ", mediatype: 'image', media: $json.image_url, caption: " + expr + " }) }}",
            }
        )
        node["credentials"] = {"httpHeaderAuth": {"id": EVOLUTION_CRED_ID, "name": EVOLUTION_CRED_NAME}}
        return
    node["parameters"].update(
        {
            "url": f"{evolution_url.rstrip('/')}/message/sendText/{instance}",
            "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth",
            "jsonBody": "={{ JSON.stringify({ number: " + json.dumps(number) + ", text: " + expr + " }) }}",
        }
    )
    node["credentials"] = {"httpHeaderAuth": {"id": EVOLUTION_CRED_ID, "name": EVOLUTION_CRED_NAME}}


def prepare(text: str, args: argparse.Namespace) -> str:
    if args.whatsapp_to:
        workflow = json.loads(text)
        for node in workflow["nodes"]:
            if is_notify_node(node):
                to_whatsapp(
                    node,
                    evolution_url=args.evolution_url,
                    instance=args.evolution_instance,
                    number=args.whatsapp_to,
                )
        return json.dumps(workflow, indent=2, ensure_ascii=False) + "\n"
    if args.notify_url:
        return text.replace(PLACEHOLDER, args.notify_url)
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--dst", required=True)
    parser.add_argument("--notify-url")
    parser.add_argument("--whatsapp-to")
    parser.add_argument("--evolution-url")
    parser.add_argument("--evolution-instance")
    args = parser.parse_args()

    if args.notify_url and args.whatsapp_to:
        raise SystemExit("Use --notify-url OU --whatsapp-to, não os dois.")
    if args.whatsapp_to:
        if not re.fullmatch(r"[0-9]{10,15}", args.whatsapp_to):
            raise SystemExit("--whatsapp-to: só dígitos com código do país, ex.: 5531999999999.")
        if not (args.evolution_url and args.evolution_instance):
            raise SystemExit("--whatsapp-to exige --evolution-url e --evolution-instance.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", args.evolution_instance):
            raise SystemExit("--evolution-instance: só letras, números, '-' e '_'.")

    dst = Path(args.dst)
    dst.mkdir(parents=True, exist_ok=True)
    for src in sorted(Path(args.src).glob("*.json")):
        (dst / src.name).write_text(prepare(src.read_text(encoding="utf-8"), args), encoding="utf-8")


if __name__ == "__main__":
    main()
