# Watchlist (DB-backed)

> The watchlist source of truth moved from this file into the
> `watchlist` table in Neon (see `sql/007_watchlist.sql`) so the
> Telegram bot can mutate it directly. Cron briefs and MCP read from
> the table, not from this file.

## How to view the current watchlist

- **Telegram**: `/watchlist`
- **Claude app via MCP**: `w_watchlist()` tool
- **Direct SQL**: `SELECT * FROM watchlist WHERE status='active'`

## How to add / remove a name

- **Telegram**: `/watch <ticker> [reason]` and `/unwatch <ticker>`
- **Claude app**: ask the project; it calls the bot or writes via the
  appropriate tool
- **Direct SQL**: `INSERT INTO watchlist ...` (writer DSN only)

See [README.md](README.md) for lifecycle conventions.
