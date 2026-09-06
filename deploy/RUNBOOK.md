# Deploy na VPS (com n8n e Supabase self-hosted já rodando)

Este runbook parte do seu cenário: a VPS já tem **n8n** e **Supabase
self-hosted** no ar, e um domínio apontado para ela. Nada aqui toca nesses dois
serviços — o backend sobe ao lado deles.

**Princípio que guia todo o resto:** nenhum passo publica porta em 80/443, nem
mexe no proxy reverso que já serve o n8n e o Supabase. Se algum comando pedir
isso, você leu errado — pare e me chame.

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
# Nome do container do Postgres do Supabase (geralmente supabase-db)
docker ps --format '{{.Names}}' | grep -i -E 'supabase|db'

# Rede Docker em que ele está — anote, vai virar SUPABASE_NETWORK
docker inspect supabase-db -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}'

# O n8n está na mesma rede? Se sim, ele fala com o backend sem passar pela internet
docker inspect n8n -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}'

# Qual proxy reverso já está servindo 80/443
docker ps --format '{{.Names}}\t{{.Image}}' | grep -i -E 'caddy|nginx|traefik|proxy'
ss -tlnp | grep -E ':(80|443)\s'

# Confirme que a 8000 está livre no host
ss -tlnp | grep ':8000\s' || echo "porta 8000 livre"
```

Guarde: **nome do container do Postgres**, **nome da rede**, **qual proxy**.

---

## 3. Criar o banco e a role da aplicação

A role `app_backend` é dona das tabelas — é isso que faz a RLS não trancar a
própria aplicação (no Postgres, o dono da tabela não é submetido à RLS dela).
Ela **não** é superusuário e **não** tem acesso ao banco `postgres` do Supabase.

Gere a senha e guarde num gerenciador de senhas antes de continuar:

```bash
openssl rand -hex 32
```

```bash
docker exec -it supabase-db psql -U postgres -v ON_ERROR_STOP=1 <<'SQL'
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
docker exec supabase-db psql -U postgres -tAc \
  "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname='app_backend'"
# esperado: app_backend|f|f
```

---

## 4. Trazer o código e configurar

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
| `SUPABASE_NETWORK` | a rede que você anotou no passo 2 |
| `DATABASE_URL` | a senha do passo 3; ajuste o host se o container não for `supabase-db` |
| `N8N_API_KEY` | `openssl rand -hex 32` — é o que o n8n vai mandar no header |
| `JWT_SECRET` | **o mesmo `JWT_SECRET` do `.env` do seu Supabase** |

O `JWT_SECRET` precisa bater com o do Supabase porque é com ele que o backend
vai validar o login do dashboard na Fase 7. Divergiu, o dashboard não entra.

Deixe `MOCK_MARKETPLACE`, `MOCK_ADS` e `DRY_RUN` em `true` neste primeiro
deploy. Assim nada externo é tocado e nenhum centavo é gasto enquanto você
confere se subiu direito.

---

## 5. Migrar e subir

As migrations rodam num passo **explícito**, não no boot do container. É de
propósito: se o app fizer rollback, o schema não volta sozinho junto — você
decide quando o banco muda.

```bash
cd ~/mp

# Constrói a imagem
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod build

# Aplica o schema (idempotente — pode rodar de novo sem medo)
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod \
  run --rm backend alembic upgrade head

# Sobe
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod up -d
```

Verifique:

```bash
curl -s http://127.0.0.1:8000/api/v1/health | python3 -m json.tool
```

Esperado: `"status": "ok"`, `"database": "up"` e o bloco `mode` com os três
trilhos em `true`.

---

## 6. Publicar no domínio

Escolha **só o snippet do proxy que você já usa**. Não suba um segundo proxy.

Troque `mp.seudominio.com.br` pelo subdomínio que você apontou para a VPS.

### Caddy

```caddyfile
mp.seudominio.com.br {
    reverse_proxy 127.0.0.1:8000
}
```

```bash
caddy reload --config /etc/caddy/Caddyfile   # ou: docker exec caddy caddy reload ...
```

O Caddy tira o certificado Let's Encrypt sozinho e renova.

### nginx

Emita o certificado primeiro:

```bash
certbot --nginx -d mp.seudominio.com.br
```

```nginx
server {
    listen 443 ssl http2;
    server_name mp.seudominio.com.br;

    ssl_certificate     /etc/letsencrypt/live/mp.seudominio.com.br/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mp.seudominio.com.br/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
nginx -t && systemctl reload nginx
```

### Traefik (por labels)

Adicione ao serviço `backend` em `deploy/docker-compose.prod.yml`:

```yaml
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.mp.rule=Host(`mp.seudominio.com.br`)"
      - "traefik.http.routers.mp.entrypoints=websecure"
      - "traefik.http.routers.mp.tls.certresolver=letsencrypt"
      - "traefik.http.services.mp.loadbalancer.server.port=8000"
```

E coloque o backend na rede do Traefik.

Teste de fora:

```bash
curl -s https://mp.seudominio.com.br/api/v1/health
```

---

## 7. Ligar o n8n

Se o n8n estiver **na mesma rede Docker** (passo 2), use o nome do container.
O tráfego nem sai da máquina, então não depende do proxy nem do certificado:

```
http://mp-backend:8000/api/v1/...
```

Se estiver fora, use `https://mp.seudominio.com.br/api/v1/...`.

Nos dois casos, toda chamada precisa do header:

```
X-API-Key: <o N8N_API_KEY do seu .env.prod>
```

Guarde essa chave numa **credencial do n8n** (Header Auth), não escrita dentro
dos nós — assim ela não vaza quando você exportar um workflow.

---

## 8. Backup

O Supabase self-hosted guarda tudo num volume Docker. Um `docker volume rm` sem
querer leva junto todo o histórico de decisões — que é append-only justamente
porque não pode ser perdido.

```bash
mkdir -p ~/backups
cat > ~/backup-mp.sh <<'EOF'
#!/bin/bash
set -euo pipefail
STAMP=$(date +%Y%m%d-%H%M)
docker exec supabase-db pg_dump -U postgres -Fc mp \
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
docker exec supabase-db psql -U postgres -c "CREATE DATABASE mp_restore_test OWNER app_backend;"
docker exec -i supabase-db pg_restore -U postgres -d mp_restore_test < ~/backups/mp-XXXX.dump
docker exec supabase-db psql -U postgres -d mp_restore_test -c "SELECT count(*) FROM config_parameters;"
docker exec supabase-db psql -U postgres -c "DROP DATABASE mp_restore_test;"
```

---

## 9. Atualizar depois

```bash
cd ~/mp
git pull

docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod build
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod \
  run --rm backend alembic upgrade head
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod up -d

curl -s http://127.0.0.1:8000/api/v1/health
```

Rode o `alembic upgrade head` sempre **antes** do `up -d`: o código novo pode
depender de coluna nova.

---

## 10. Quando algo der errado

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `database: down` no health | `DATABASE_URL` errado, ou backend fora da rede do Supabase | `docker logs mp-backend`; confira `SUPABASE_NETWORK` e o nome do container |
| `could not translate host name "supabase-db"` | o container do Postgres tem outro nome | ajuste o host no `DATABASE_URL` com o nome do passo 2 |
| Container reinicia em loop | config inválida — a app recusa subir de propósito | `docker logs mp-backend`; a mensagem diz qual variável está incoerente |
| `permission denied for table ...` | migrations rodaram por outra role que não `app_backend` | as tabelas precisam ser dela; veja o passo 3 |
| 502 no domínio | proxy apontando para porta errada | o backend escuta em `127.0.0.1:8000` |
| n8n toma 401 | header ausente ou chave diferente | `X-API-Key` tem que bater com `N8N_API_KEY` |

Ver logs e status:

```bash
docker logs -f mp-backend
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.prod ps
```

---

## 11. Conferência de segurança

Depois do deploy, confirme os três pontos:

```bash
# 1. As tabelas NÃO aparecem na API REST do Supabase
#    (esperado: erro/vazio — elas estão em outro banco)
curl -s "https://SEU-SUPABASE/rest/v1/ai_decisions?apikey=SUA_ANON_KEY" | head -c 300

# 2. RLS ligada nas 30 tabelas
docker exec supabase-db psql -U postgres -d mp -tAc \
  "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='public' AND c.relkind='r' AND c.relrowsecurity"
# esperado: 30

# 3. A API não responde sem TLS a partir da internet
curl -s -m 5 http://SEU_IP_PUBLICO:8000/api/v1/health || echo "fechado, como esperado"
```
