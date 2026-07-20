# Deep-dive framework (Mode 2)

Institutional, filing-grade single-name analysis — the "hedge-fund deep-dive" workflow. Produce the
depth of a sell-side/buy-side memo: business & moat, segments, financials, valuation, competition,
risks, catalysts, entry. Always close with the **two-question verdict** (good business? / good entry?).

## Contents
1. Snapshot
2. Segment analysis (where money is vs where growth is)
3. Moat & competitive gating (the barbell frame)
4. Financials (how to read them honestly)
5. Valuation triangulation
6. Risks
7. Catalysts & timeline
8. Optionality
9. Confirmed-vs-open (filing-grade discipline)
10. Filing sources — what to fetch and where
11. Deliverables

---

## 1. Snapshot
Price; P/E (trailing + forward if estimable); P/B; dividend yield; market cap; shares out; net
cash/debt; ROE (through-cycle); gross/operating margin; 52-week range; beta. Pull via `q_valuation`
+ `yf_info`/`yf_financials` (note the Yahoo financials tool can throw a Timestamp error — fall back
to TW-native tools and filings). Flag immediately if the P/E is high because earnings *collapsed*
(fallen-angel) vs because the stock is expensive.

## 2. Segment analysis
Get the **audited segment note** (annual report Note on operating segments) — it's authoritative,
unlike media product-line estimates. For each segment: % of revenue, YoY, segment margin. Then the
finer product-line view from the investor deck.
- Separate **where the money is** (biggest revenue segment = the swing factor) from **where the
  growth/margin is** (a small high-margin segment can be the narrative driver but won't move near-term
  EPS). Name which segment actually drives the next 1–2 quarters of earnings.

## 3. Moat & competitive gating — the barbell frame
Map competitors **per segment** (named, not hand-waved) and how *gated* each is. A recurring, useful
finding: moats are often a **barbell** — the deepest gates (certification, defect-intolerance,
proprietary process/IP) protect the *smallest, highest-margin* segments, while the *bulk* of revenue
is a "wide-but-shallow" position (category leadership + relationships, but still competing against
lower-cost rivals). That barbell explains mid-tier margins (better than commodity, short of monopoly)
and a value multiple. The re-rating thesis is usually "market starts paying for the crown-jewel IP /
optionality rather than just the cyclical bulk."
- Gating axes to assess: certification/regulatory (e.g., NADCAP, medical, export-controlled
  materials), switching costs, capital intensity, proprietary process/material science, share/scale,
  customer captivity. Note where the competition is China-price-driven (a share war, not a moat).
- Use `web_search` for named competitors, market shares, and industry structure; verify shares
  across sources (they vary).

## 4. Financials — read them honestly
- **Normalize.** Don't anchor to a post-boom peak year; use a mid-cycle year for earning power.
- **Decompose the drop.** A big EPS fall is often *mechanical* — e.g., an FX swing (a gain one year
  → loss the next is a double-counted headwind), not structural decay. Separate operating decline
  from FX/one-offs.
- **Quarterly path.** Reconstruct from cumulative filings to find the trough and the recovery slope.
- **Margin inflection** is usually the missing piece: revenue can recover on low-margin volume while
  operating margin still drifts down. Identify the quarter where the margin turn *should* show, and
  make it the key proof point.
- **Balance sheet.** Net cash, debt/equity, current ratio, dividend consistency — the "fortress"
  check that underwrites the downside.

## 5. Valuation triangulation
Anchor on the scenario/multiple frame for cyclicals; use DCF as an intrinsic cross-check; use the
dividend as a floor.
- **Scenario:** bull / base / bear = FY-forward EPS × exit P/E, with probabilities → weighted target.
- **DCF (FCFF):** WACC + terminal growth; the *signal* isn't the point estimate, it's whether even
  conservative inputs land well above price (⇒ market pricing ~no recovery ⇒ burden of proof on the
  bear).
- **Dividend floor:** payout ÷ a normalized yield → the price where income buyers step in.
- **Comps:** peers' P/Es are often flattered by trough earnings; the cleaner cross-cycle read is P/B
  and yield vs ROE.

## 6. Risks
Enumerate honestly: primary cyclicality driver; **customer concentration — verify against the
audited filing**, do not trust third-party "X% to one customer" claims; FX; raw-material/input
costs; execution (esp. long-cycle segments); governance (family control, pledge ratios, independent
directors). Rank by likelihood × impact.

## 7. Catalysts & timeline
Near-term: monthly revenue (~10th of month), quarterly earnings (get the date), ex-dividend.
Structural: capacity ramps, new-market entries, corporate actions (spin-offs, restructurings —
verify on MOPS). Build a dated calendar; note which catalysts cluster (e.g., a name + its peers all
reporting the same week = triangulated confirm/deny).

## 8. Optionality
List free call options (spin-offs, new end-markets — robots, AI power, defense, etc.). **Credit them
as free options you're not paying for at a low multiple; never underwrite them as the thesis.** For
each, note stage (MOU / design-in / sample / revenue) and whether the company's approach is even the
likely winner (e.g., carbon-fibre vs PEEK vs metal for robot structures is unsettled). Narrative
optionality is years from financials and de-rates hard on any slip.

## 9. Confirmed-vs-open (filing-grade discipline)
Explicitly split what's **confirmed against audited filings** from what's **still open / to
monitor**. This is what makes it filing-grade rather than a hot take. If a datum is from media or an
estimate, say so.

## 10. Filing sources — what to fetch and where
Tools give price/flow/valuation/monthly-revenue; the *qualitative* depth (business, segments, risk
factors, customers, capacity, governance) needs primary filings. Direct the user to:
- **MOPS 公開資訊觀測站 (mops.twse.com.tw)** — the master repository: **年報 (annual report)** (most
  valuable: operations, segment note, customers, capacity, governance, dividends), **財務報表**
  (audited FY + quarterly consolidated), **月營收** (monthly revenue), **重大訊息** (material
  announcements), **法說會** investor-conference decks.
- **Company IR site** — investor decks, product/segment detail.
- **TWSE / TPEX** — listing data.
If the user can fetch a filing, ask for the latest **annual report** and **most recent quarterly
financials** first — they close the most gaps.

## 11. Deliverables
Ask the user which format (per SKILL.md "Output — ask each run"). For files, use the document skills:
- **Investment memo (.docx):** use the `docx` skill. Sections: exec summary + recommendation box
  (fair value, weighted target, current, total return, risk/reward), company snapshot, segments,
  thesis, financials, valuation, risks, catalysts, technical/entry, confirmed-vs-open, sources,
  disclaimer.
- **Valuation model (.xlsx):** use the `xlsx` skill — scenario table, DCF, comps, sensitivity.
- **Dashboard (.html):** self-contained (Chart.js), KPI cards, price+volume, revenue/EPS, segment
  mix, scenarios with an interactive EPS×exit-P/E calculator, quarterly path, and the entry plan.
Present via `present_files`. Every deliverable carries the "not investment advice / not a licensed
adviser" line.
