#!/usr/bin/env bash
# Primeiro deploy do MP na VPS que já roda Coolify + Supabase self-hosted.
# Automatiza os passos 2, 4, 5 e 6 do deploy/RUNBOOK.md.
#
# O que este script FAZ (e pede confirmação antes de qualquer escrita):
#   1. descobre o container do Postgres do Supabase e as redes Docker
#   2. cria no Postgres do Supabase a role `app_backend` e o banco `mp`
#      (a role NÃO é superusuário; anon/authenticated/PUBLIC ficam sem acesso ao banco)
#   3. lê do .env do Supabase só: JWT_SECRET, ANON_KEY e a URL pública — e escreve
#      deploy/.env.prod (chmod 600). Nenhum segredo é impresso na tela.
#   4. constrói as imagens, aplica as migrations e sobe os containers
#
# O que NÃO faz: não cria DNS, não mexe no Traefik/Coolify, não toca em nenhum outro
# banco do Postgres, não publica porta no host.
#
# Uso:
#   bash deploy/bootstrap.sh --email voce@exemplo.com [--dry-run] [--yes] [--skip-up]
#
# É reexecutável: se deploy/.env.prod já existe, pula a criação do banco e do arquivo e
# segue direto para build, migrate e up.

set -euo pipefail

DOMAIN="mp.dsearch.com.br"
EMAIL=""
DRY_RUN=0
ASSUME_YES=0
SKIP_UP=0

usage() {
  sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --email)   EMAIL="${2:-}"; shift 2 ;;
    --domain)  DOMAIN="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --yes)     ASSUME_YES=1; shift ;;
    --skip-up) SKIP_UP=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "Opção desconhecida: $1" >&2; usage 1 ;;
  esac
done

if [ -z "$EMAIL" ]; then
  echo "Falta --email: é quem poderá entrar no dashboard (DASHBOARD_ALLOWED_EMAILS)." >&2
  usage 1
fi

cd "$(dirname "$0")/.."
ENV_FILE="deploy/.env.prod"
COMPOSE=(docker compose -f deploy/docker-compose.prod.yml --env-file "$ENV_FILE")

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   ok  %s\n' "$*"; }
warn() { printf '   !!  %s\n' "$*"; }
die()  { printf '\nERRO: %s\n' "$*" >&2; exit 1; }
# Em dry-run, comandos que escrevem só são anunciados.
run()  { if [ "$DRY_RUN" -eq 1 ]; then printf '   [dry-run] %s\n' "$*"; else "$@"; fi; }

confirm() {
  [ "$ASSUME_YES" -eq 1 ] && return 0
  [ "$DRY_RUN" -eq 1 ] && return 0
  read -r -p "$1 [s/N] " answer
  [ "$answer" = "s" ] || [ "$answer" = "S" ] || die "Cancelado."
}

command -v docker >/dev/null || die "docker não encontrado."
[ -f deploy/docker-compose.prod.yml ] || die "Rode a partir do repositório (deploy/docker-compose.prod.yml não existe)."

# ---------------------------------------------------------------- 1. descoberta
say "1/6 Descobrindo o ambiente (só leitura)"

mapfile -t DB_CONTAINERS < <(docker ps --format '{{.Names}}' | grep -E '^supabase-db-' || true)
[ "${#DB_CONTAINERS[@]}" -eq 1 ] || die "Esperava 1 container 'supabase-db-*', achei ${#DB_CONTAINERS[@]}: ${DB_CONTAINERS[*]:-nenhum}."
DB_CONTAINER="${DB_CONTAINERS[0]}"
SUPABASE_UUID="${DB_CONTAINER#supabase-db-}"
SUPABASE_ENV="/data/coolify/services/${SUPABASE_UUID}/.env"
ok "Postgres do Supabase: $DB_CONTAINER"

docker ps --format '{{.Names}}' | grep -x 'coolify-proxy' >/dev/null || die "Container 'coolify-proxy' (Traefik) não está rodando."
PROXY_NETWORK="coolify"
docker inspect coolify-proxy -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' \
  | grep -x "$PROXY_NETWORK" >/dev/null || die "O Traefik não está na rede '$PROXY_NETWORK'."
ok "Rede do Traefik: $PROXY_NETWORK"

SUPABASE_NETWORK="$SUPABASE_UUID"
docker inspect "$DB_CONTAINER" -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' \
  | grep -x "$SUPABASE_NETWORK" >/dev/null || die "O Postgres não está na rede '$SUPABASE_NETWORK'."
ok "Rede do Supabase: $SUPABASE_NETWORK"

for name in mp-backend mp-frontend; do
  if docker ps -a --format '{{.Names}}' | grep -x "$name" >/dev/null; then
    warn "Container '$name' já existe (o 'up' vai recriá-lo)."
  fi
done

# Só confere que o arquivo e as chaves existem; nenhum valor é impresso.
[ -r "$SUPABASE_ENV" ] || die "Não consigo ler $SUPABASE_ENV (rode como root)."
env_value() {
  # Valor de CHAVE=valor sem aspas. Última ocorrência vence, como no docker compose.
  # O Coolify escreve referências (JWT_SECRET=${SERVICE_PASSWORD_JWT}); resolve até 5 níveis.
  local key="$1" value depth
  for depth in 1 2 3 4 5; do
    value="$({ grep -E "^${key}=" "$SUPABASE_ENV" || true; } | tail -n1 | cut -d= -f2- \
      | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")"
    if [[ "$value" =~ ^\$\{([A-Za-z0-9_]+)\}$ ]]; then
      key="${BASH_REMATCH[1]}"
    else
      printf '%s' "$value"
      return 0
    fi
  done
  return 1
}
for key in JWT_SECRET SUPABASE_ANON_KEY POSTGRES_PASSWORD; do
  [ -n "$(env_value "$key")" ] || die "$key vazio ou ausente em $SUPABASE_ENV."
done
# O banco `mp` precisa ser criado por um SUPERUSUÁRIO. No Supabase o 'postgres' não é
# superuser, e o contorno óbvio (GRANT app_backend TO CURRENT_USER) DERRUBA o backend do
# Postgres com segfault na imagem supabase/postgres 15.8.1.085 — reproduzido numa cópia
# descartável e uma vez em produção. Por isso: supabase_admin, sem nenhum GRANT de role.
psql_admin() {
  docker exec -i -e PGPASSWORD="$(env_value POSTGRES_PASSWORD)" "$DB_CONTAINER" \
    psql -h 127.0.0.1 -U supabase_admin -d postgres "$@"
}

SUPABASE_URL="$(env_value API_EXTERNAL_URL)"
if [ -z "$SUPABASE_URL" ]; then
  fqdn="$(env_value SERVICE_FQDN_SUPABASEKONG)"
  [ -n "$fqdn" ] || die "Não achei a URL pública do Supabase (API_EXTERNAL_URL / SERVICE_FQDN_SUPABASEKONG)."
  SUPABASE_URL="https://${fqdn#https://}"
fi
ok "Supabase: JWT_SECRET e ANON_KEY presentes; URL pública $SUPABASE_URL"

# O Supabase precisa assinar com HS256 — é o que o backend valida.
ANON_ALG="$(env_value SUPABASE_ANON_KEY | cut -d. -f1 | python3 -c "
import sys, base64, json
h = sys.stdin.read().strip()
print(json.loads(base64.urlsafe_b64decode(h + '=' * (-len(h) % 4))).get('alg', '?'))")"
[ "$ANON_ALG" = "HS256" ] || die "A anon key do Supabase usa '$ANON_ALG', não HS256; o backend precisa de ajuste antes do deploy."
ok "Assinatura do JWT do Supabase: HS256"

IS_SUPER="$(psql_admin -tAc "SELECT rolsuper FROM pg_roles WHERE rolname='supabase_admin'" 2>/dev/null || true)"
[ "$IS_SUPER" = "t" ] || die "Não consegui entrar como supabase_admin (superuser) com a POSTGRES_PASSWORD do .env do Supabase."
ok "Acesso de superusuário do Supabase confirmado (só será usado para criar o banco mp)"

HAS_USER="$(docker exec "$DB_CONTAINER" psql -U postgres -tAc \
  "SELECT count(*) FROM auth.users WHERE lower(email)=lower('${EMAIL//\'/}')" 2>/dev/null || echo 0)"
if [ "${HAS_USER:-0}" -ge 1 ]; then
  ok "O e-mail $EMAIL existe como usuário do Supabase"
else
  warn "O e-mail $EMAIL NÃO existe no Supabase Auth: crie o usuário no Studio (Authentication > Users) antes de logar."
fi

# ------------------------------------------------------------------------ DNS
say "2/6 DNS"
SERVER_IP="$(curl -s -m 8 https://api.ipify.org || true)"
DNS_IP="$(getent hosts "$DOMAIN" | awk '{print $1; exit}' || true)"
DNS_OK=0
if [ -z "$DNS_IP" ]; then
  warn "$DOMAIN não resolve. Crie o registro A '${DOMAIN%%.*}' -> ${SERVER_IP:-<IP da VPS>}."
elif [ -n "$SERVER_IP" ] && [ "$DNS_IP" != "$SERVER_IP" ]; then
  warn "$DOMAIN aponta para $DNS_IP, mas esta VPS é $SERVER_IP."
else
  DNS_OK=1
  ok "$DOMAIN -> $DNS_IP (esta VPS)"
fi
if [ "$DNS_OK" -eq 0 ]; then
  warn "Sem DNS correto o Let's Encrypt falha: o script constrói e migra, mas NÃO sobe os containers."
fi

# ------------------------------------------------------------------ 3. banco + env
if [ -f "$ENV_FILE" ]; then
  say "3/6 Banco e $ENV_FILE"
  ok "$ENV_FILE já existe: pulando criação do banco e do arquivo (reexecução)."
else
  say "3/6 Criando banco e $ENV_FILE"

  ROLE_EXISTS="$(docker exec "$DB_CONTAINER" psql -U postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='app_backend'")"
  DB_EXISTS="$(docker exec "$DB_CONTAINER" psql -U postgres -tAc "SELECT 1 FROM pg_database WHERE datname='mp'")"
  ROLE_OWNS_DB="$(docker exec "$DB_CONTAINER" psql -U postgres -tAc "SELECT 1 FROM pg_database d JOIN pg_roles r ON r.oid=d.datdba WHERE r.rolname='app_backend'")"
  if [ -n "$DB_EXISTS" ] || [ -n "$ROLE_OWNS_DB" ]; then
    die "O banco 'mp' já existe (ou a role 'app_backend' já é dona de algum banco), mas $ENV_FILE não. Não sei a senha da role e não vou sobrescrever nada: resolva à mão (ex.: ALTER ROLE app_backend PASSWORD '...') e crie o $ENV_FILE a partir de deploy/.env.prod.example."
  fi
  if [ -n "$ROLE_EXISTS" ]; then
    # Sobra de uma execução anterior que parou antes de criar o banco: a role não possui
    # nada, então é seguro só trocar a senha (a antiga se perdeu junto com a execução).
    ROLE_STATEMENT="ALTER ROLE app_backend WITH LOGIN PASSWORD :'pw';"
    ROLE_ACTION="ALTER ROLE app_backend (já existe, sem banco: só troca a senha por uma gerada)"
    warn "A role 'app_backend' já existe sem banco (execução anterior interrompida): vou reaproveitá-la."
  else
    ROLE_STATEMENT="CREATE ROLE app_backend WITH LOGIN PASSWORD :'pw';"
    ROLE_ACTION="CREATE ROLE app_backend LOGIN (sem superuser, sem bypassrls) COM SENHA GERADA"
  fi

  cat <<EOF

   Vou executar no Postgres do Supabase ($DB_CONTAINER):
     $ROLE_ACTION
     CREATE DATABASE mp OWNER app_backend   (executado como supabase_admin)
     REVOKE ALL ON DATABASE mp FROM PUBLIC, anon, authenticated
   e escrever $ENV_FILE (chmod 600) com segredos lidos de $SUPABASE_ENV.
   Nenhum outro banco do cluster é tocado.
EOF
  confirm "Continuar?"

  if [ "$DRY_RUN" -eq 1 ]; then
    run docker exec -i "$DB_CONTAINER" psql -U postgres "<CREATE ROLE/DATABASE app_backend + mp>"
    run "escrever $ENV_FILE"
  else
    PW="$(openssl rand -hex 32)"
    N8N_KEY="$(openssl rand -hex 32)"

    # A senha viaja por stdin (\set), não por argv: não aparece em `ps`.
    {
      printf "\\\\set pw '%s'\n" "$PW"
      printf '%s\n' "$ROLE_STATEMENT"
      cat <<'SQL'
CREATE DATABASE mp OWNER app_backend;
REVOKE ALL ON DATABASE mp FROM PUBLIC;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    REVOKE ALL ON DATABASE mp FROM anon;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    REVOKE ALL ON DATABASE mp FROM authenticated;
  END IF;
END $$;
SQL
    } | psql_admin -v ON_ERROR_STOP=1 -q

    docker exec "$DB_CONTAINER" psql -U postgres -tAc \
      "SELECT rolname||'|super='||rolsuper||'|bypassrls='||rolbypassrls FROM pg_roles WHERE rolname='app_backend'"
    ok "Role e banco criados (esperado: super=f, bypassrls=f)"

    umask 077
    export PW N8N_KEY EMAIL DOMAIN PROXY_NETWORK SUPABASE_NETWORK DB_CONTAINER SUPABASE_URL
    export JWT_SECRET_VALUE ANON_KEY_VALUE
    JWT_SECRET_VALUE="$(env_value JWT_SECRET)"
    ANON_KEY_VALUE="$(env_value SUPABASE_ANON_KEY)"

    # awk lê os valores do ambiente: nada passa por argv nem por escape de sed.
    awk '
      BEGIN {
        v["MP_DOMAIN"]                = ENVIRON["DOMAIN"]
        v["PROXY_NETWORK"]            = ENVIRON["PROXY_NETWORK"]
        v["SUPABASE_NETWORK"]         = ENVIRON["SUPABASE_NETWORK"]
        v["DATABASE_URL"]             = "postgresql+psycopg://app_backend:" ENVIRON["PW"] "@" ENVIRON["DB_CONTAINER"] ":5432/mp"
        v["N8N_API_KEY"]              = ENVIRON["N8N_KEY"]
        v["JWT_SECRET"]               = ENVIRON["JWT_SECRET_VALUE"]
        v["DASHBOARD_ALLOWED_EMAILS"] = ENVIRON["EMAIL"]
        v["VITE_SUPABASE_URL"]        = ENVIRON["SUPABASE_URL"]
        v["VITE_SUPABASE_ANON_KEY"]   = ENVIRON["ANON_KEY_VALUE"]
      }
      {
        split($0, kv, "=")
        if (kv[1] in v) { print kv[1] "=" v[kv[1]]; seen[kv[1]] = 1 } else print
      }
      END { for (k in v) if (!(k in seen)) { print "FALTOU " k > "/dev/stderr"; exit 1 } }
    ' deploy/.env.prod.example > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    unset PW N8N_KEY JWT_SECRET_VALUE ANON_KEY_VALUE
    ok "$ENV_FILE escrito (chmod 600). Guarde uma cópia num gerenciador de senhas."
    git check-ignore -q "$ENV_FILE" && ok "$ENV_FILE está no .gitignore" || warn "$ENV_FILE NÃO está ignorado pelo git!"
  fi
fi

# ------------------------------------------------------------- 4. build + migrate
say "4/6 Construindo imagens"
if [ "$DRY_RUN" -eq 1 ] && [ ! -f "$ENV_FILE" ]; then
  run "${COMPOSE[*]} build"
else
  confirm "Construir as imagens (pode levar alguns minutos)?"
  run "${COMPOSE[@]}" build
fi

say "5/6 Aplicando migrations (alembic upgrade head)"
if [ "$DRY_RUN" -eq 1 ] && [ ! -f "$ENV_FILE" ]; then
  run "${COMPOSE[*]} run --rm backend alembic upgrade head"
else
  run "${COMPOSE[@]}" run --rm backend alembic upgrade head
fi

# ---------------------------------------------------------------------- 6. up
say "6/6 Subindo"
if [ "$SKIP_UP" -eq 1 ]; then
  warn "--skip-up: nada foi iniciado."
elif [ "$DNS_OK" -eq 0 ]; then
  warn "DNS ainda não aponta para esta VPS: NÃO subi os containers."
  warn "Depois de criar o registro A e ele propagar, rode de novo: bash deploy/bootstrap.sh --email $EMAIL"
else
  confirm "Subir mp-backend e mp-frontend agora?"
  run "${COMPOSE[@]}" up -d

  if [ "$DRY_RUN" -eq 0 ]; then
    echo "   aguardando o backend…"
    healthy=0
    for _ in $(seq 1 30); do
      if body="$(docker exec mp-backend python -c \
        "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/api/v1/health').read().decode())" 2>/dev/null)"; then
        healthy=1; break
      fi
      sleep 2
    done
    [ "$healthy" -eq 1 ] || die "mp-backend não respondeu ao /health. Veja: docker logs mp-backend"
    case "$body" in
      *'"database":"up"'*|*'"database": "up"'*) ;;
      *) warn "Backend no ar, mas o banco não está 'up': $body" ;;
    esac
    ok "Backend respondendo: $body"

    echo "   conferindo o domínio (o certificado pode levar alguns segundos)…"
    for _ in $(seq 1 12); do
      code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "https://$DOMAIN/api/v1/health" || true)"
      [ "$code" = "200" ] && break
      sleep 5
    done
    if [ "${code:-}" = "200" ]; then ok "https://$DOMAIN respondendo"; else warn "https://$DOMAIN devolveu '${code:-sem resposta}'. Se for certificado, espere um minuto e veja: docker logs coolify-proxy"; fi
  fi
fi

say "Pronto"
cat <<EOF
   Trilhos: o deploy sobe com MOCK_MARKETPLACE, MOCK_ADS e DRY_RUN em true
   e AI_AUTONOMY_LEVEL=1 — nada externo é tocado e nenhum centavo é gasto.

   Próximos passos:
     - Dashboard: https://$DOMAIN  (entre com $EMAIL)
     - n8n: aponte para http://mp-backend:8000/api/v1/... com o header X-API-Key
       (o valor está em N8N_API_KEY no $ENV_FILE; guarde-o como credencial do n8n)
     - Confirme o CORS do Kong para https://$DOMAIN se o login falhar no navegador
     - Backup do banco 'mp': veja a seção 9 do deploy/RUNBOOK.md
EOF
