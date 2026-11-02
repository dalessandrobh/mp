#!/usr/bin/env bash
# Importa os workflows do MP (n8n/workflows/*.json) e a credencial da API no SEU n8n.
#
# O que faz:
#   - confere que o container do n8n existe e alcança o mp-backend pela rede Docker
#   - cria/atualiza a credencial "MP API Key" (header X-API-Key) com o N8N_API_KEY do
#     deploy/.env.prod — o valor nunca é impresso
#   - importa os 9 workflows com IDs fixos (reexecutar ATUALIZA os do MP; não toca nos
#     seus outros workflows)
#   - com --notify-url, grava o webhook de notificação nos nós que notificam
#   - ou, com --whatsapp-to, faz os nós notificarem por WhatsApp via Evolution API
#     (a chave da Evolution vai pela variável EVOLUTION_APIKEY, nunca por argumento)
#   - com --only NOME (ex.: 09_daily_report), importa SÓ esse(s) workflow(s) — os outros, que
#     você já tenha ativado, não são tocados. Com --no-credentials, assume que as credenciais
#     já existem no n8n (não pede a chave da Evolution de novo)
#   - com --activate, publica pela CLI (MAS os agendamentos só entram em vigor após
#     REINICIAR o n8n — veja o aviso abaixo)
#
# O que NÃO faz: não reinicia o n8n, não mexe em nenhum workflow que não seja do MP.
#
# CAMINHO RECOMENDADO num n8n que já atende outras automações (ex.: chat do WhatsApp):
#   rode SEM --activate e ligue o botão "Active" de cada workflow "MP …" no editor. Ativar
#   pela interface vale na hora, sem reiniciar. Reiniciar o n8n derruba TODOS os seus
#   workflows por alguns segundos, e um webhook que chegar nesse intervalo pode se perder.
#
# ATENÇÃO: importar sem --activate deixa os workflows do MP INATIVOS, inclusive os que
# você já tivesse ativado numa execução anterior.
#
# Uso:
#   bash n8n/install.sh [--container NOME] [--env-file deploy/.env.prod]
#                       [--notify-url URL] [--activate] [--dry-run]
#                       [--only 09_daily_report ...] [--no-credentials]
#   EVOLUTION_APIKEY=... bash n8n/install.sh --whatsapp-to 5531999999999 \
#                       --evolution-url https://evo.exemplo.com --evolution-instance mp-alertas

set -euo pipefail

CONTAINER=""
ENV_FILE="deploy/.env.prod"
NOTIFY_URL=""
WHATSAPP_TO=""
EVOLUTION_URL=""
EVOLUTION_INSTANCE=""
ACTIVATE=0
DRY_RUN=0
NO_CREDENTIALS=0
ONLY=()

while [ $# -gt 0 ]; do
  case "$1" in
    --container)  CONTAINER="${2:-}"; shift 2 ;;
    --env-file)   ENV_FILE="${2:-}"; shift 2 ;;
    --notify-url) NOTIFY_URL="${2:-}"; shift 2 ;;
    --whatsapp-to) WHATSAPP_TO="${2:-}"; shift 2 ;;
    --evolution-url) EVOLUTION_URL="${2:-}"; shift 2 ;;
    --evolution-instance) EVOLUTION_INSTANCE="${2:-}"; shift 2 ;;
    --activate)   ACTIVATE=1; shift ;;
    --dry-run)    DRY_RUN=1; shift ;;
    --only)       ONLY+=("${2:-}"); shift 2 ;;
    --no-credentials) NO_CREDENTIALS=1; shift ;;
    -h|--help)    sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Opção desconhecida: $1" >&2; exit 1 ;;
  esac
done

cd "$(dirname "$0")/.."
say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   ok  %s\n' "$*"; }
warn() { printf '   !!  %s\n' "$*"; }
die()  { printf '\nERRO: %s\n' "$*" >&2; exit 1; }

PLACEHOLDER="https://CONFIGURE-O-WEBHOOK-DE-NOTIFICACAO.invalid/"
WORKFLOWS_DIR="n8n/workflows"

say "1/4 Conferindo o ambiente"
command -v docker >/dev/null || die "docker não encontrado."
[ -d "$WORKFLOWS_DIR" ] || die "$WORKFLOWS_DIR não existe (rode a partir do repositório)."
[ -f "$ENV_FILE" ] || die "$ENV_FILE não existe: rode o deploy/bootstrap.sh antes."

if [ -z "$CONTAINER" ]; then
  mapfile -t CANDIDATES < <(docker ps --format '{{.Names}}' | grep -i n8n | grep -iv -E 'db|postgres|redis' || true)
  [ "${#CANDIDATES[@]}" -eq 1 ] || die "Não consegui escolher o container do n8n (${CANDIDATES[*]:-nenhum}). Use --container NOME."
  CONTAINER="${CANDIDATES[0]}"
fi
docker ps --format '{{.Names}}' | grep -x "$CONTAINER" >/dev/null || die "Container '$CONTAINER' não está rodando."
ok "n8n: $CONTAINER ($(docker exec "$CONTAINER" n8n --version 2>/dev/null | tail -1))"

N8N_KEY="$({ grep -E '^N8N_API_KEY=' "$ENV_FILE" || true; } | tail -n1 | cut -d= -f2-)"
[ -n "$N8N_KEY" ] || die "N8N_API_KEY vazio em $ENV_FILE."
ok "N8N_API_KEY lido de $ENV_FILE"

# O n8n chama http://mp-backend:8000 pelo nome: precisa estar numa rede em comum.
if docker exec "$CONTAINER" wget -qO- -T 8 http://mp-backend:8000/api/v1/health >/dev/null 2>&1; then
  ok "O n8n alcança o mp-backend pela rede Docker"
else
  warn "O n8n NÃO alcança http://mp-backend:8000. Conecte-o à rede do mp-backend:"
  warn "    docker network connect coolify $CONTAINER"
fi

if [ -n "$WHATSAPP_TO" ]; then
  [ -z "$NOTIFY_URL" ] || die "Use --notify-url OU --whatsapp-to, não os dois."
  if [ "$NO_CREDENTIALS" -eq 0 ]; then
    [ -n "${EVOLUTION_APIKEY:-}" ] || die "Defina EVOLUTION_APIKEY (a chave da INSTÂNCIA na Evolution) no ambiente."
  fi
  ok "Notificações por WhatsApp (Evolution, instância '$EVOLUTION_INSTANCE') para ${WHATSAPP_TO:0:4}…${WHATSAPP_TO: -2}"
  if curl -s -m 8 -o /dev/null -w '%{http_code}' "$EVOLUTION_URL/" 2>/dev/null | grep -q '^200$'; then
    ok "Evolution respondendo em $EVOLUTION_URL"
  else
    warn "A Evolution não respondeu 200 em $EVOLUTION_URL (confira a URL)."
  fi
elif [ -z "$NOTIFY_URL" ]; then
  warn "Sem --notify-url nem --whatsapp-to: as notificações ficarão apontando para um endereço inválido."
  warn "Passe o webhook (Slack, Discord, Mattermost…), ou --whatsapp-to, ou edite os nós 'Notificar' depois."
fi

say "2/4 Preparando os arquivos (em diretório temporário, apagado ao final)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"; docker exec -u 0 "$CONTAINER" rm -rf /tmp/mp-import >/dev/null 2>&1 || true' EXIT
chmod 700 "$TMP"
mkdir "$TMP/workflows"

# Só os workflows pedidos (ou todos): o resto fica de fora do import, logo não é desativado.
SRC="$WORKFLOWS_DIR"
if [ "${#ONLY[@]}" -gt 0 ]; then
  SRC="$TMP/selected"; mkdir "$SRC"
  for name in "${ONLY[@]}"; do
    [ -f "$WORKFLOWS_DIR/$name.json" ] || die "Workflow '$name' não existe em $WORKFLOWS_DIR."
    cp "$WORKFLOWS_DIR/$name.json" "$SRC/"
  done
  ok "importando só: ${ONLY[*]}"
fi
python3 n8n/prepare.py --src "$SRC" --dst "$TMP/workflows" \
  ${NOTIFY_URL:+--notify-url "$NOTIFY_URL"} \
  ${WHATSAPP_TO:+--whatsapp-to "$WHATSAPP_TO" --evolution-url "$EVOLUTION_URL" --evolution-instance "$EVOLUTION_INSTANCE"}
ok "$(find "$TMP/workflows" -name '*.json' | wc -l) workflows preparados"

if [ "$NO_CREDENTIALS" -eq 0 ]; then
N8N_KEY="$N8N_KEY" WHATSAPP_TO="$WHATSAPP_TO" python3 - "n8n/credential.template.json" "$TMP/credential.json" <<'PY'
import json, os, sys
cred = json.load(open(sys.argv[1]))
cred[0]["data"]["value"] = os.environ["N8N_KEY"]
if os.environ["WHATSAPP_TO"]:
    # A Evolution autentica por header `apikey`. A chave vem do ambiente, não de argv.
    cred.append(
        {
            "id": "mpEvolution0000001",
            "name": "MP Evolution API Key",
            "type": "httpHeaderAuth",
            "data": {"name": "apikey", "value": os.environ["EVOLUTION_APIKEY"]},
        }
    )
with open(sys.argv[2], "w") as out:
    json.dump(cred, out)
PY
chmod 600 "$TMP/credential.json"
ok "credencial montada (valor não impresso)"
else
  ok "credenciais: mantendo as que já estão no n8n (--no-credentials)"
fi

if [ "$DRY_RUN" -eq 1 ]; then
  say "--dry-run: nada foi importado"
  exit 0
fi

say "3/4 Importando no n8n"
docker exec -u 0 "$CONTAINER" rm -rf /tmp/mp-import
docker cp "$TMP" "$CONTAINER:/tmp/mp-import"
# docker cp preserva dono e modo do host (root, 700); o n8n roda como o usuário 'node'.
docker exec -u 0 "$CONTAINER" chown -R "$(docker exec "$CONTAINER" id -u):$(docker exec "$CONTAINER" id -g)" /tmp/mp-import
if [ "$NO_CREDENTIALS" -eq 0 ]; then
  docker exec "$CONTAINER" n8n import:credentials --input=/tmp/mp-import/credential.json 2>&1 | grep -v 'Error tracking' || true
fi
docker exec "$CONTAINER" n8n import:workflow --separate --input=/tmp/mp-import/workflows 2>&1 | grep -v 'Error tracking' || true

say "4/4 Ativação"
if [ "$ACTIVATE" -eq 1 ]; then
  for f in "$TMP"/workflows/*.json; do
    id="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['id'])" "$f")"
    docker exec "$CONTAINER" n8n publish:workflow --id="$id" 2>&1 | grep -v 'Error tracking' | tail -1 || true
  done
  warn "Publicado pela CLI: os agendamentos SÓ entram em vigor após  docker restart $CONTAINER"
  warn "Isso derruba TODOS os workflows deste n8n por alguns segundos (inclusive os que não são do MP)."
  warn "Alternativa sem restart: ligue o botão 'Active' de cada workflow 'MP …' no editor do n8n."
else
  ok "Workflows importados INATIVOS. Para ativar SEM reiniciar o n8n: abra cada workflow 'MP …'"
  ok "no editor e ligue o botão 'Active' (vale na hora; não afeta os seus outros workflows)."
fi

cat <<'FIM'

   Próximos passos:
     1. No n8n, abra "MP 01 · Descoberta e qualificação" e clique em "Execute workflow" para testar.
     2. Em cada workflow > Settings, confirme "Error workflow" = "MP 00 · Erro em workflow".
     3. Ative cada "MP …" pelo botão Active (sem reiniciar o n8n).
     4. O backend segue em DRY_RUN=true por padrão: os workflows rodam, mas nada é gravado
        de verdade até você mudar DRY_RUN (veja docs/runbook.md).
FIM
