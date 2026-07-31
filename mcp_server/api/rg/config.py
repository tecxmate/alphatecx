"""Risk Guard tunables and fixed copy.

Every number the M1 scorer keys off lives here, per PRD §7 ("閾值進 config,
改動記 CHANGELOG"). Changing a threshold and re-running `python -m
riskguard.replay` is the intended calibration loop; editing scoring.py is not.

The 兵法 quote table also lives here. PRD §6 and §5-M7 make it a code-review
acceptance condition that it never reaches a scoring or triggering path — it is
looked up once, at message-format time, keyed by an alert kind that has already
been decided. Keeping it in config (data, not logic) is what makes a violation
visible in review.
"""
from __future__ import annotations

# ── M1 subitem thresholds ───────────────────────────────────────────────────

# 1. TAIEX vs moving averages. Points stack: below both MAs scores 1 + 2 = 3.
MA_SHORT = 20
MA_LONG = 60
PTS_BELOW_MA_SHORT = 1
PTS_BELOW_MA_LONG = 2

# 2. Breadth — 5-day mean of adv / (adv + dec) over TWSE common stock only
#    (MI_INDEX 漲跌證券數合計, the 股票 column, which excludes warrants and ETFs).
BREADTH_WINDOW = 5
BREADTH_BAD = 0.40
BREADTH_WEAK = 0.45
PTS_BREADTH_BAD = 2
PTS_BREADTH_WEAK = 1

# Same-session breadth shock. The 5-day mean measures regime and is deliberately
# slow, which means it cannot see a one-day collapse: 2026-07-07 printed
# 128↑/892↓ — a ratio of 0.126, one of the worst sessions of the correction —
# while its 5-day mean sat at 0.517 because 07-01…07-06 had been strong. Under
# the mean alone that session scored zero on breadth.
#
# Subitem 2 takes the WORSE of the two readings, never their sum, so the
# subitem keeps the maximum weight of 2 that PRD §5 assigns it. Thresholds are
# read off the 2026-06/07 distribution: crash sessions printed 0.08–0.13,
# ordinary weak days 0.35–0.45, rallies 0.85+.
BREADTH_DAY_BAD = 0.15
BREADTH_DAY_WEAK = 0.25

# 3. Margin — retail leverage still climbing into a falling index is the
#    "everyone is still holding" signal, so both halves must be true.
MARGIN_WINDOW = 5
MARGIN_GROWTH_PCT = 3.0
PTS_MARGIN = 2

# 4. Foreign futures positioning (TAIFEX 臺股期貨 外資及陸資 多空未平倉口數淨額).
#
#    Scores the *change*, not the level, which is a deliberate departure from
#    PRD §5 #4 ("淨空>20,000口"). Measured over 2026-06/07 the level never left
#    65k–86k net short — on +4.20% days and on the −6.47% crash alike — so the
#    PRD's threshold was crossed on literally every session and the subitem
#    contributed a constant +2 to every score. A constant is not a signal; it
#    just moved the whole scale up and made 🟢 reachable only when all four
#    other subitems were zero.
#
#    The level is a structural hedge against cash holdings. What carries
#    information is foreigners *adding* to that hedge. Thresholds are the 10th
#    percentile (≈ −8,000) and roughly the median (≈ −4,000) of the observed
#    5-session change over the same window.
#
#    Honest limitation, measured: even this does not separate the 2026-07
#    correction cleanly — 7/24 (−2.67%) saw foreigners *cut* net short by
#    ~9,900 while 6/30 (+2.50%) saw them add ~6,600. On this sample the series
#    carries little directional signal at any horizon, so it is deliberately
#    capped at a small contribution rather than allowed to dominate.
FUT_CHANGE_WINDOW = 5
FUT_ADD_SHORT_HEAVY = 8_000   # added this many contracts to net short
FUT_ADD_SHORT_MILD = 4_000

# Absolute net-short level, PRD §5. Scored since 2026-07-31 at [niko]'s
# direction; FUT_ADD_SHORT_* above survive only as reported context.
#
# MEASURED CONSEQUENCE, accepted knowingly: across the 37 sessions on record the
# foreign net OI ran -63,168 to -86,189, so FUT_NET_SHORT_HEAVY is crossed on
# 100% of days. This subitem is therefore a constant +2, not a discriminator —
# it cannot tell a day foreigners piled into shorts from one they covered.
#
# What that costs, precisely: the floor score becomes 2 against a green band of
# ≤2. A calm market is still green, but with zero margin — one point from any
# other subitem turns it yellow. Scores read 2 higher than the acceptance table
# assumed.
#
# To make it discriminate again, move the threshold to something the data
# actually crosses (a rolling percentile, or ~80,000). See docs/wiki/log.md.
FUT_NET_SHORT_HEAVY = 20_000
FUT_NET_SHORT_MILD = 10_000

PTS_FUT_HEAVY = 2
PTS_FUT_MILD = 1

# 5. Single-day drawdown. Takes the worse band, does not stack.
DAY_DROP_MILD = -2.0
DAY_DROP_HEAVY = -3.5
PTS_DAY_MILD = 1
PTS_DAY_HEAVY = 2

# ── Score → light bands ─────────────────────────────────────────────────────

SCORE_YELLOW = 3   # 3
SCORE_RED = 4      # ≥4
# PRD §5 bands 0–2 / 3–4 / ≥5 were written when subitem 4 scored the futures
# *level*, which added a constant +2 to every session (see below). With that
# padding removed every score dropped by ~2, so the cutoffs move with it.
# Calibrated on 2026-06-25→07-30 via `python -m riskguard.replay`: ≥4 marks
# exactly the seven PRD §7 acceptance sessions plus 6/26 (−3.64%), while calm
# and rising days land at 0–1. Raising it back to 5 fails the 7/24 row.

# ── Light hysteresis (PRD §5 M1 v1.1) ───────────────────────────────────────
#
# Downgrades toward green are gated; upgrades toward red are immediate. Without
# this, 7/30 (−0.26% after a −4.65% / −3.76% pair) and 7/31 (+8.0%) each flip
# the light on a single quiet or violent day — exactly the failure the replay
# table exists to catch.

# 紅轉黃: the index must have held above its prior low this many sessions running.
RED_TO_YELLOW_HOLD_DAYS = 2
# The window whose minimum close defines "前低".
PRIOR_LOW_WINDOW = 10
# 黃轉綠: back above MA20, or this many consecutive higher closes.
YELLOW_TO_GREEN_UP_STREAK = 3

# ── M2 stop alerts ──────────────────────────────────────────────────────────

DEFAULT_HARD_STOP_PCT = 10.0

# PRD §5 M2 v1.1: the 28.6 case proved a close-only rule plus a human hand
# takes four days to execute. Every exit alert carries this instruction.
CONDITIONAL_ORDER_ADVICE = (
    "建議改掛券商觸價條件單(觸價=出場線下一檔、市價、長效),把執行交給機器"
)

# ── M2b settlement ──────────────────────────────────────────────────────────

SETTLEMENT_LAG_DAYS = 2          # T+2, counted in trading days
SETTLEMENT_LOOKAHEAD_DAYS = 3    # check the next 3 settlement dates
SETTLEMENT_WARN_LEAD_DAYS = 2    # alert at least this many days ahead

# Taiwan retail cost model, used to turn a reported fill into a settlement
# amount. Brokerage 0.1425% with the common 6折 discount; the sell side also
# pays 0.3% 證交稅. Minimum NT$20 fee per side.
BROKER_FEE_RATE = 0.001425
BROKER_FEE_DISCOUNT = 0.6
BROKER_FEE_MIN = 20
SECURITIES_TAX_RATE = 0.003
SHARES_PER_LOT = 1000

# ── Entry checklist (PRD §5 M2) ─────────────────────────────────────────────

MAX_5D_GAIN_PCT = 15.0        # Q3 — the 175 vertical-run block
MAX_CASH_USE_PCT = 70.0       # Q6 — single buy ≤ 70% of available cash

# The only two verdict strings the checklist may produce. There is no "buy"
# phrasing anywhere in Risk Guard, by design (PRD §0, §5 M2).
VERDICT_BLOCKED = "今天不買。原因:"
VERDICT_CLEAR = "沒有阻止你的理由"

# ── 兵法 copy layer (PRD §6) ────────────────────────────────────────────────
#
# Pure presentation. Keyed by alert kind; read only by messages.format_alert().
SUNZI_BY_KIND = {
    "risk_light_red": "不可勝者,守也",
    "risk_light_green": "善戰者,無智名,無勇功",
    "stop_warn": "小敵之堅,大敵之擒也",
    "stop_exit": "小敵之堅,大敵之擒也",
    "anomaly_limit_open": "兵貴勝,不貴久",
    "anomaly_crash": "兵貴勝,不貴久",
    "checklist_block": "勝兵先勝而後求戰",
    "sector_exit": "避實而擊虛",
    "settlement_gap": "多算勝,少算不勝",
}

LIGHT_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
SEVERITY_EMOJI = {"info": "ℹ️", "warn": "⚠️", "critical": "🚨"}
