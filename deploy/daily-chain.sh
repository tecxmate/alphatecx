#!/bin/sh
# Post-close chain, mirroring the step order and failure semantics of
# .github/workflows/daily_harvest.yml. Read that file before changing this one;
# the two are meant to stay in step.
#
# Failure semantics are not uniform, and the differences are deliberate:
#   harvest    — fatal. Everything downstream reads what it writes.
#   brief      — soft (continue-on-error upstream). Message layer; the data is
#                already committed by the time it runs.
#   riskguard  — FATAL, and pointedly not continue-on-error upstream: a silent
#                failure here is a stop-loss alert that never fired. A non-zero
#                exit also skips the remaining steps, matching how the
#                workflow's `if: success()` guards behave.
#   leadlag    — soft. Feeds the q_lead_lag MCP tool; stale beats absent.
#   thesis     — soft. Telegram/digest heartbeat.
#
# Deliberately absent versus the workflow: dashboard.build,
# build_ticker_pages and correlation_snapshot. Their only output is static
# files under mcp_server/api/static/ that get committed back to main — and this
# worker does not commit. Running them here would burn minutes producing
# artifacts nobody reads. Dashboard regeneration stays on GitHub Actions.
set -u

soft() {
    echo "--- (soft) $* ---"
    if ! "$@"; then
        echo "WARN: '$*' exited $? — continuing, matching continue-on-error upstream"
    fi
}

hard() {
    echo "--- (fatal) $* ---"
    if ! "$@"; then
        echo "FATAL: '$*' exited $? — aborting chain"
        exit 1
    fi
}

echo "=== post-close chain starting $(date -Iseconds) ==="

hard python -m src.harvester.daily
soft python -m src.cron.brief --mode post_close
hard python -m riskguard.pipeline --mode post_close
soft python -m src.quant.leadlag --window 60 --max-lag 7
soft python -m src.cron.thesis_status

echo "=== post-close chain finished $(date -Iseconds) ==="
