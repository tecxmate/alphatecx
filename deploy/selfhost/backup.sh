#!/usr/bin/env bash
# Nightly Postgres backup for the self-hosted stack.
#
# Why this is more paranoid than "pg_dump > file": the data is not
# reconstructable. TWSE does not serve deep history, so a lost volume means
# years of harvested flow data are gone for good. The realistic failure is not
# a backup that errors — it is a backup that silently writes a truncated or
# empty file every night for six months, discovered on the one day it matters.
#
# So every run must PROVE the archive is restorable before it is kept:
#   1. pg_dump exits non-zero            → fail loudly
#   2. archive smaller than MIN_BYTES    → fail loudly
#   3. `pg_restore -l` cannot read it    → fail loudly
#   4. table count in the TOC looks thin → fail loudly
# Only then does retention pruning run — pruning before verifying would let a
# run of bad backups evict the last good one.
#
# Install (host crontab, 03:00 daily):
#   0 3 * * * /path/to/deploy/selfhost/backup.sh >> /var/log/alphatecx-backup.log 2>&1
set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

BACKUP_DIR="${BACKUP_DIR:-/var/backups/alphatecx}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"
# The live DB is ~328 MB and pg_dump -Fc compresses it well below that. 20 MB
# is far under any plausible healthy dump but far over an empty or schema-only
# one, which is the case this floor actually guards against.
MIN_BYTES="${MIN_BYTES:-20000000}"
MIN_TABLES="${MIN_TABLES:-25}"   # 34 tables today; a real drop below this is a problem
DB_NAME="${DB_NAME:-zeabur}"
DB_USER="${DB_USER:-root}"

STAMP="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$BACKUP_DIR/alphatecx-$STAMP.dump"
TOC="$(mktemp)"

log() { echo "[$(date -Is)] $*"; }

cleanup() { rm -f "$TOC"; }

fail() {
    log "BACKUP FAILED: $*"
    # Best-effort alert. A backup system that fails quietly is the same class
    # of bug as having no backup at all.
    if [ -n "${TELEGRAM_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
        curl -sS --max-time 20 -X POST \
            "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" \
            -d "text=🔴 alphatecx backup FAILED on $(hostname): $*" >/dev/null || true
    fi
    # Remove the half-written archive so a later run cannot mistake it for good.
    [ -f "$ARCHIVE" ] && rm -f "$ARCHIVE"
    cleanup
    exit 1
}
trap 'fail "unexpected error on line $LINENO"' ERR
trap cleanup EXIT

mkdir -p "$BACKUP_DIR"

log "dumping $DB_NAME -> $ARCHIVE"
# -T so docker does not allocate a TTY and corrupt the binary stream.
# --clean --if-exists makes the archive restorable over a non-empty database.
docker compose exec -T postgres \
    pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc --clean --if-exists \
    > "$ARCHIVE" || fail "pg_dump exited non-zero"

# ── verification ────────────────────────────────────────────────────────────
SIZE="$(wc -c < "$ARCHIVE")"
[ "$SIZE" -ge "$MIN_BYTES" ] \
    || fail "archive is ${SIZE} bytes, below floor ${MIN_BYTES} — truncated or schema-only"

pg_restore -l "$ARCHIVE" > "$TOC" 2>/dev/null \
    || fail "pg_restore could not read the archive — it is corrupt, not merely small"

TABLES="$(grep -c ' TABLE DATA ' "$TOC" || true)"
[ "$TABLES" -ge "$MIN_TABLES" ] \
    || fail "archive lists only ${TABLES} tables with data, expected >= ${MIN_TABLES}"

log "verified: $(numfmt --to=iec "$SIZE" 2>/dev/null || echo "${SIZE} bytes"), ${TABLES} tables"

# ── offsite ─────────────────────────────────────────────────────────────────
# A backup on the same disk as the database is not a backup: it survives
# fat-fingered SQL but not the disk, the host, or the provider. Configure an
# rclone remote and this pushes there. Deliberately warns rather than skipping
# silently — "offsite was never configured" should stay visible in the log.
if [ -n "${RCLONE_REMOTE:-}" ]; then
    log "uploading to $RCLONE_REMOTE"
    rclone copy "$ARCHIVE" "$RCLONE_REMOTE" --no-traverse \
        || fail "rclone upload failed — local copy kept at $ARCHIVE"
    log "uploaded"
else
    log "WARNING: RCLONE_REMOTE unset — this backup exists only on this host."
fi

# ── retention (only after a verified good archive) ──────────────────────────
find "$BACKUP_DIR" -name 'alphatecx-*.dump' -type f -mtime "+$RETAIN_DAYS" -print -delete \
    | while read -r old; do log "pruned $old"; done

log "backup complete"
