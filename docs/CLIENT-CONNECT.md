# Connecting to Alphatecx in Claude

Alphatecx gives Claude live ground-truth data on Taiwan equities (institutional
flow, supply-chain structure, dividends, risk) so its answers to your investing
questions are grounded in real numbers rather than guesses.

You'll connect it once as a **connector** inside Claude. After that, just ask
Claude your questions normally — it will pull Alphatecx data as needed.

**You need two things from us:**
1. A connector URL — `https://alphatecx-mcp.zeabur.app/mcp`
2. Your personal access key — a string starting with `atx_…` (we send this to you
   privately; treat it like a password and don't share it).

---

## Set it up (about 2 minutes)

You can use Alphatecx in the Claude web app, the mobile app, or the desktop app.

1. Open Claude → **Settings → Connectors** (also called "Custom connectors").
2. Choose **Add custom connector**.
3. Paste the **connector URL** above and confirm.
4. Claude will open a short **sign-in page for Alphatecx**. In the password box,
   paste the **access key** we gave you (`atx_…`) and approve.
5. Done — Alphatecx now appears in your connectors.

To check it works, ask Claude something like:

> "Using Alphatecx, what's the recent institutional flow on 2330?"

If Claude returns data with a source and date, you're connected.

---

## Good to know

- **One key = you.** Your access key identifies your account. Don't share it; if
  it leaks, tell us and we'll issue a new one.
- **It's data, not advice.** Every Alphatecx response is labelled as informational
  market data, not investment advice — Claude uses it to inform its answers, and
  you make your own decisions.
- **If access stops working**, your subscription period may have ended — just get
  in touch with us.

## Trouble connecting?

- "Couldn't sign in" → double-check the access key was pasted with no extra spaces.
- The connector doesn't appear → make sure you added it under *Custom connectors*
  and completed the sign-in step (step 4), not just pasted the URL.
- Still stuck → send us the exact message Claude showed and we'll sort it.
