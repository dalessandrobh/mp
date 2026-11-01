# Deploy na VPS (Coolify + Traefik, com n8n e Supabase self-hosted já rodando)

Este runbook parte do seu cenário real: a VPS já tem **Coolify** com **Traefik**
servindo 80/443, **Supabase self-hosted** e **n8n** no ar. Nada aqui toca nesses
serviços — o backend e o frontend sobem ao lado deles.

**Princípio que guia todo o resto:** nenhum passo publica porta no host, nem
mexe no proxy que já serve o que está no ar. O Traefik alcança os containers
pela rede Docker e faz o TLS. Se algum comando pedir para publicar porta, você
leu errado — pare e me chame.

**Endereço final:**

| URL | Serve |
|---|---|
| `https://mp.dsearch.com.br/` | frontend (React, bundle estático em nginx) |
| `https://mp.dsearch.com.br/api/v1/*` | backend (FastAPI) |

Mesma origem para os dois: sem CORS para manter, um só certificado, um só
registro DNS.

---

## 1. Por que um banco `mp` separado

O PostgREST do Supabase publica o schema `public` do banco `postgres` na
internet para quem tiver a chave `anon`. Se as 30 tabelas da plataforma fossem
para lá, `ai_decisions`, `budget_ledger` e `performance_daily` ficariam
legíveis de fora.

Por isso as tabelas vão para um **banco `mp` dedicado**, no mesmo Postgres do
Supabase. O PostgREST se conecta ao banco `postgres` e não enxerga outro banco
do cluster — a exposição deixa de existir por construção, não por configuração.

Como segunda camada, a migration `ce194330e97c` ainda liga RLS em todas as
tabelas e revoga acesso de `anon` e `authenticated`. Se algum dia alguém mover
as tabelas para o banco errado, elas continuam trancadas.

---

## 2. Descobrir o ambiente

Rode na VPS. Nenhum destes comandos escreve nada nem imprime segredo:

```bash
# Container do Postgres do Supabase. No Coolify o nome leva o UUID da aplicação
# (ex.: supabase-db-y1eg2mz3a73wkjhz7vty7bzg) — NÃO é só "supabase-db".
docker ps --format '{{.Names}}' | grep -i supabase-db

# Rede desse container — vira SUPABASE_NETWORK
docker inspect <nome-do-container-acima> \
  -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}'

# Rede em que o Traefik enxerga containers — vira PROXY_NETWORK (normalmente `coolify`)
docker inspect coolify-proxy \
  -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}'

# Nome do container do n8n e suas redes (para o passo 8)
docker ps --format '{{.Names}}' | grep -i n8n
```

Guarde: **nome do container do Postgres**, **SUPABASE_NETWORK**, **PROXY_NETWORK**.

> **Não tente usar a porta 8000 do host.** Ela é do próprio Coolify
> (`0.0.0.0:8000->8080`). Por isso este deploy não publica porta nenhuma: quem
> alcança os containers é o Traefik, pela rede Docker.

---

## 3. Apontar o DNS

No painel de DNS de `dsearch.com.br`, crie:

| Tipo | Nome | Valor |
|---|---|---|
| A | `mp` | o IP público da VPS (o mesmo de `dsearch.com.br`) |

Confirme antes de seguir — o Let's Encrypt usa desafio HTTP e **falha se o DNS
ainda não propagou**:

```bash
getent hosts mp.dsearch.com.br
```

---

## 4. Criar o banco e a role da aplicação

A role `app_backend` é dona das tabelas — é isso que faz a RLS não trancar a
própria aplicação (no Postgres, o dono da tabela não é submetido à RLS dela).
Ela **não** é superusuário e **não** tem acesso ao banco `postgres` do Supabase.

Gere a senha e guarde num gerenciador de senhas antes de continuar:

```bash
openssl rand -hex 32
```

Troque `SUPABASE_DB` pelo nome do container que você anotou no passo 2:

```bash
docker exec -it SUPABASE_DB psql -U postgres -v ON_ERROR_STOP=1 <<'SQL'
-- Troque COLE_A_SENHA_AQUI pela senha gerada acima.
CREATE ROLE app_backend WITH LOGIN PASSWORD 'COLE_A_SENHA_AQUI';
CREATE DATABASE mp OWNER app_backend;

-- Ninguém além do dono entra neste banco.
REVOKE ALL ON DATABASE mp FROM PUBLIC;

-- As roles do PostgREST não têm nada a fazer aqui.
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
```

Confirme que a role não é superusuário:

```bash
docker exec SUPABASE_DB psql -U postgres -tAc \
  "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname='app_backend'"
# esperado: app_backend|f|f
```

---

## 5. Trazer o código e configurar

```bash
git clone https://github.com/dalessandrobh/mp.git
cd mp
git checkout claude/affiliate-automation-platform-tp21lt

cp deploy/.env.prod.example deploy/.env.prod
chmod 600 deploy/.env.prod
nano deploy/.env.prod
```

Preencha:

| Variável | De onde vem |
|---|---|
| `MP_DOMAIN` | `mp.dsearch.com.br` |
| `PROXY_NETWORK` | a rede do Traefik do passo 2 (normalmente `coolify`) |
| `SUPABASE_NETWORK` | a rede do Postgres do passo 2 |
| `DATABASE_URL` | a senha do passo 4 + o **nome do container** do Postgres como host |
| `N8N_API_KEY` | `openssl rand -hex 32` — é o que o n8n vai mandar no header |
| `JWT_SECRET` | **o mesmo `JWT_SECRET` do `.env` do seu Supabase** |
| `DASHBOARD_ALLOWED_EMAILS` | seu(s) e-mail(s), separados por vírgula. **Obrigatória:** sem ela o backend não sobe em produção. Todo usuário do seu Supabase tem JWT válido; esta lista é quem pode de fato aprovar recomendações |
| `VITE_SUPABASE_URL` | URL pública do seu Supabase (a que o Studio/Kong expõe) |
| `VITE_SUPABASE_ANON_KEY` | a `ANON_KEY` do `.env` do Supabase. É pública por desenho, mas entra no bundle **no build**: mudar exige `docker compose build frontend` |

O `JWT_SECRET` precisa bater com o do Supabase porque é com ele que o backend
vai validar o login do dashboard. Divergiu, o dashboard não entra.

O login usa o Supabase Auth direto do navegador: crie seu usuário no Studio (Authentication →
Users) e confirme que o Kong do Supabase aceita requisições vindas de `https://MP_DOMAIN`
(CORS). Se o login falhar com erro de rede no console do navegador, é isso.

Deixe `MOCK_MARKETPLACE`, `MOCK_ADS` e `DRY_RUN` em `true` neste primeiro
deploy. Assim nada externo é tocado e nenhum centavo é gasto enquanto você
confere se subiu direito — e o próprio dashboard mostra esses três trilhos na
tela inicial.

---

## 6. Migrar e subir

As migrations rodam num passo **explícito**, não no boot do container. É de
propósito: se o app fizer rollback, o schema não volta sozinho junto — você
decide quando o banco muda.

```bash
cd ~/mp
COMPOSE="docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod"

# Constrói backend e frontend
$COMPOSE build

# Aplica o schema (idempotente — pode rodar de novo sem medo)
$COMPOSE run --rm backend alembic upgrade head

# Sobe
$COMPOSE up -d
```

Verifique de dentro da rede Docker (não há porta no host para consultar):

```bash
docker exec mp-backend python -c \
  "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/api/v1/health').read().decode())"
```

Esperado: `"status": "ok"`, `"database": "up"` e o bloco `mode` com os três
trilhos em `true`.

---

## 7. Conferir o domínio

O Traefik descobre os dois serviços pelas labels no compose e emite o
certificado sozinho. Na primeira subida isso leva alguns segundos.

```bash
# Frontend
curl -sI https://mp.dsearch.com.br/ | head -3

# Backend, no mesmo host
curl -s https://mp.dsearch.com.br/api/v1/health | python3 -m json.tool

# HTTP redireciona para HTTPS
curl -sI http://mp.dsearch.com.br/ | head -3
```

Abra `https://mp.dsearch.com.br` no navegador: a tela inicial mostra o estado do
backend, a conexão com o banco e os três trilhos de segurança.

**Como o roteamento decide quem responde:** os dois routers escutam o mesmo
host, e a prioridade desempata — `/api` tem prioridade 100, o frontend tem 10.
Qualquer caminho que não comece com `/api` cai no frontend, que devolve o
`index.html` para o react-router resolver.

---

## 8. Ligar o n8n

Se o n8n estiver na mesma rede do Traefik (`PROXY_NETWORK`), use o nome do
container. O tráfego nem sai da máquina, então não depende do proxy nem do
certificado:

```
http://mp-backend:8000/api/v1/...
```

Se estiver em outra rede, ou use `https://mp.dsearch.com.br/api/v1/...`, ou
conecte o n8n à rede:

```bash
docker network connect coolify <container-do-n8n>
```

Nos dois casos, toda chamada precisa do header:

```
X-API-Key: <o N8N_API_KEY do seu .env.prod>
```

Guarde essa chave numa **credencial do n8n** (Header Auth), não escrita dentro
dos nós — assim ela não vaza quando você exportar um workflow.

---

## 9. Backup

O Supabase self-hosted guarda tudo num volume Docker. Um `docker volume rm` sem
querer leva junto todo o histórico de decisões — que é append-only justamente
porque não pode ser perdido.

Troque `SUPABASE_DB` pelo nome do container do passo 2:

```bash
mkdir -p ~/backups
cat > ~/backup-mp.sh <<'EOF'
#!/bin/bash
set -euo pipefail
STAMP=$(date +%Y%m%d-%H%M)
docker exec SUPABASE_DB pg_dump -U postgres -Fc mp \
  > "$HOME/backups/mp-$STAMP.dump"
# Mantém 14 dias
find "$HOME/backups" -name 'mp-*.dump' -mtime +14 -delete
EOF
chmod +x ~/backup-mp.sh

# Todo dia às 03:00
(crontab -l 2>/dev/null; echo "0 3 * * * $HOME/backup-mp.sh") | crontab -
```

Teste a restauração pelo menos uma vez, num banco descartável — backup que
nunca foi restaurado não é backup:

```bash
docker exec SUPABASE_DB psql -U postgres -c "CREATE DATABASE mp_restore_test OWNER app_backend;"
docker exec -i SUPABASE_DB pg_restore -U postgres -d mp_restore_test < ~/backups/mp-XXXX.dump
docker exec SUPABASE_DB psql -U postgres -d mp_restore_test -c "SELECT count(*) FROM config_parameters;"
docker exec SUPABASE_DB psql -U postgres -c "DROP DATABASE mp_restore_test;"
```

---

## 10. Atualizar depois

```bash
cd ~/mp
git pull
COMPOSE="docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod"

$COMPOSE build
$COMPOSE run --rm backend alembic upgrade head
$COMPOSE up -d
```

Rode o `alembic upgrade head` sempre **antes** do `up -d`: o código novo pode
depender de coluna nova.

Para publicar só o frontend (mudou uma tela, o backend está igual):

```bash
$COMPOSE build frontend && $COMPOSE up -d frontend
```

---

## 11. Quando algo der errado

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `database: down` no health | `DATABASE_URL` errado, ou backend fora da rede do Supabase | `docker logs mp-backend`; confira `SUPABASE_NETWORK` e o nome do container do Postgres |
| `could not translate host name` | host do `DATABASE_URL` não é o nome real do container | use o nome completo do passo 2, com o sufixo do Coolify |
| Container reinicia em loop | config inválida — a app recusa subir de propósito | `docker logs mp-backend`; a mensagem diz qual variável está incoerente |
| 404 do Traefik no domínio | DNS não propagou, ou container fora de `PROXY_NETWORK` | `getent hosts mp.dsearch.com.br`; `docker inspect mp-frontend` e confira a rede |
| Certificado não emite | Let's Encrypt não alcançou o host pela porta 80 | confirme o DNS e que o `coolify-proxy` está de pé; veja `docker logs coolify-proxy` |
| `/api` devolvendo o HTML do frontend | prioridades invertidas nos routers | `/api` tem que ser 100 e o front 10 — confira as labels |
| n8n toma 401 | header ausente ou chave diferente | `X-API-Key` tem que bater com `N8N_API_KEY` |
| Tela do dashboard diz "Backend inacessível" | backend fora do ar ou rota `/api` não casando | rode a verificação do passo 6 e depois a do passo 7 |

Ver logs e status:

```bash
docker logs -f mp-backend
docker logs -f mp-frontend
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod ps
```

---

## 12. Conferência de segurança

Depois do deploy, confirme os quatro pontos:

```bash
# 1. As tabelas NÃO aparecem na API REST do Supabase
#    (esperado: erro/vazio — elas estão em outro banco)
curl -s "https://SEU-SUPABASE/rest/v1/ai_decisions?apikey=SUA_ANON_KEY" | head -c 300

# 2. RLS ligada nas 30 tabelas
docker exec SUPABASE_DB psql -U postgres -d mp -tAc \
  "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='public' AND c.relkind='r' AND c.relrowsecurity"
# esperado: 30

# 3. Nenhuma porta nova aberta no host pelo deploy
docker port mp-backend; docker port mp-frontend
# esperado: vazio nos dois

# 4. O dashboard não é indexável (é um painel interno)
curl -sI https://mp.dsearch.com.br/ | grep -i x-robots-tag
# esperado: X-Robots-Tag: noindex, nofollow
```
