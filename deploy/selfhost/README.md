# Self-hosting alphatecx

The whole system on one box: Postgres, the MCP server, the cron worker, the news
poller, and Caddy for TLS. Sized for a €4–5/mo VPS (2 vCPU / 4 GB / 40 GB) — the
database is ~328 MB across 34 tables, and the only real RAM consumer is polars
during the nightly harvest.

Not included on purpose: the `worker` service currently on Zeabur. It runs the
same `python -m src.news.watch` as `newswatch` and is a duplicate poller.

## Why bother

One reason above the others: **Postgres publishes no ports here.** It is reachable
only on the internal docker network. On Zeabur the database has TLS disabled and
sits behind a public TCP proxy, so credentials cross the open internet in
cleartext every time GitHub Actions harvests. Self-hosted, that exposure does not
get mitigated — it stops existing. Caddy then gives the MCP endpoint real
Let's Encrypt certificates.

## Bootstrap

Order matters. `mcp` will crash-loop until the `mcp_viewer` role exists, because
a read-only role cannot create itself.

```bash
cd deploy/selfhost
cp .env.example .env && $EDITOR .env          # fill every un-commented blank

# 1. DNS first. Caddy's ACME challenge needs MCP_DOMAIN → this host on port 80
#    BEFORE first start, or it retries into a Let's Encrypt rate limit.
dig +short "$MCP_DOMAIN"

# 2. Database alone, so the schema can be applied before anything reads it.
docker compose up -d postgres

# 3. Schema + roles. --rls is what creates mcp_viewer and grants it SELECT;
#    it reads MCP_VIEWER_PASSWORD from the repo-root .env, which must match
#    the value in this directory's .env.
docker compose run --rm --entrypoint sh cron -c \
  'MCP_VIEWER_PASSWORD="$MCP_VIEWER_PASSWORD" python apply_schema.py --rls'

# 4. Everything else.
docker compose up -d --build
curl -s "https://$MCP_DOMAIN/health"
```

### Migrating existing data

```bash
# On the old host
pg_dump "$OLD_DATABASE_URL" -Fc --clean --if-exists > alphatecx.dump

# On the new one — restore BEFORE step 3 above; the dump carries the schema.
docker compose exec -T postgres \
  pg_restore -U root -d zeabur --clean --if-exists < alphatecx.dump
```

Roles do not travel in a `pg_dump`. `mcp_viewer` must be created separately —
that is what `apply_schema.py --rls` is for, and it is the step people forget.

### Telegram

The webhook must be re-pointed at the new host, and the secret is set by the same
call that sets the URL:

```bash
curl -X POST "https://api.telegram.org/bot$TELEGRAM_TOKEN/setWebhook" \
  -d "url=https://$MCP_DOMAIN/bot/webhook" \
  -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
```

## Backups

**Set this up before you trust the box with anything.** TWSE does not serve deep
history, so a lost volume is years of harvested flow data gone permanently.

```bash
sudo crontab -e
0 3 * * * RCLONE_REMOTE=b2:alphatecx-backups /srv/alphatecx/deploy/selfhost/backup.sh \
          >> /var/log/alphatecx-backup.log 2>&1
```

`backup.sh` refuses to keep an archive it cannot prove is restorable: it checks
the exit code, a size floor, that `pg_restore -l` can read the file, and that the
table count looks sane — and only prunes old backups after all four pass, so a
run of bad backups can never evict the last good one. It alerts to Telegram on
failure if `TELEGRAM_TOKEN`/`TELEGRAM_CHAT_ID` are exported.

Without `RCLONE_REMOTE` the backup sits on the same disk as the database, which
survives bad SQL but not a dead host. The script logs a warning every night in
that state, deliberately.

Test a restore at least once, into a scratch database. An untested backup is a
hypothesis.

## Keep GitHub Actions

Do not migrate the workflows away, even after this is running. They are free,
external, and — because `CRON_TELEGRAM_TOKEN` starts blank to avoid duplicate
alerts — currently the only thing that tells you a scheduled run failed. An alarm
that lives on the host it is monitoring is not an alarm.

## Operating

```bash
docker compose logs -f cron              # supercronic + job output
docker compose exec postgres psql -U root -d zeabur
docker compose exec cron deploy/daily-chain.sh    # run the post-close chain now
docker compose up -d --build             # redeploy after a git pull
```

A redeploy that straddles a scheduled slot **misses it silently** — supercronic
does not backfill. Avoid rebuilding at 16:30 or 08:30 Taipei.
