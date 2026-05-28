# Seller Checklist — What You Need Before Selling to Beginners

If you intend to sell `ICTSessionsEA` (or this whole package) to others, here's what you actually need to put together. This is the difference between "I have an EA" and "I have a product."

---

## 1. Product packaging (must-have)

### 1.1 Compiled binary (.ex5) — the actual deliverable
- **Compile** `ICTSessionsEA.mq5` in MetaEditor → produces `ICTSessionsEA.ex5`
- **Ship only the `.ex5`** — never share the `.mq5` source unless you want buyers to see/modify your code
- The `.ex5` runs identically but the source is hidden

### 1.2 Account-locked license (recommended)
Add an `InpAccountNumbers` input that whitelists specific MT5 account numbers. In `OnInit()`:

```cpp
input string InpAccountNumbers = "12345678,87654321";  // CSV of allowed accounts

int OnInit() {
   long acc = AccountInfoInteger(ACCOUNT_LOGIN);
   // parse InpAccountNumbers, check if acc is in list
   if(!IsAccountAllowed(acc)) {
      Alert("This EA is not licensed for this account.");
      return INIT_FAILED;
   }
   ...
}
```

Then for each customer, you compile a custom version with their account number, or you build a license-key system. Without this, the buyer can share the EA with friends and you get one sale for many users.

### 1.3 Expiry / trial mode
Add an `InpExpiryDate = "2026.12.31"` input. In `OnInit()`, compare to `TimeCurrent()` and refuse to run after that date. Lets you sell monthly subscriptions, or hand out 7-day trials.

### 1.4 Installation guide (1 page)
Step-by-step with screenshots:
1. Where to download from
2. How to copy files into MT5 data folder
3. How to compile (or that .ex5 is already compiled)
4. How to attach to chart
5. Confirmation that it's working

You already have most of this in `USER_GUIDE.md` — strip it down to "first 30 minutes" for the install guide.

---

## 2. Required disclaimers (legal must-have)

Every page of marketing AND the installation document must include:

> **Risk Disclaimer:** Trading synthetic indices carries substantial risk of loss. Past performance does not guarantee future results. The backtest results presented are simulated and based on historical data with optimistic assumptions (look-ahead bias on same-bar TP/SL). Live results will differ. Never trade money you cannot afford to lose. This EA is a tool — you are responsible for monitoring and managing your account. We do not provide financial advice.

If you're in South Africa, also include:

> The author is not a registered FSP (Financial Services Provider) and does not offer financial advice. This product is sold for educational and tool-use purposes only.

Without this you risk regulatory issues with FSCA in SA, FCA in UK, etc.

---

## 3. Realistic expectations (ethics + retention)

If you sell with promises like "10% per day guaranteed" you'll get refund requests and chargebacks within a week. Be honest:

| Honest claim | Why it's honest |
|---|---|
| "Backtested +0.841R per trade over 2,656 trades, all 9 months positive" | Verifiable in scanner_results.csv |
| "Expect ~5–10 trades per day on V25 M5" | Based on actual trade frequency |
| "Live performance typically 60–80% of backtest" | Industry-standard estimate |
| "Recommended minimum starting balance: $50–$100" | Min lot 0.5 × tick value × SL = real $/trade |
| "Daily stop at 3R caps loss at ~8% of $9 account" | Just math |

What NOT to claim:
- ❌ "Guaranteed profits"
- ❌ "X% per month"
- ❌ "Risk-free"
- ❌ "Beats the market"
- ❌ Screenshot of one big winning day as "typical"

---

## 4. Support infrastructure

When you sell to beginners, **80% of their questions are install/setup**, not strategy. Have ready:

- **Email or Telegram channel** for support
- **FAQ document** covering top 20 install/run issues
- **Video walkthrough** (record once, share forever): 10-min screen recording of the full install process
- **Discord/Telegram group** for community Q&A (so users help each other and reduce your load)

Top 20 expected questions:
1. "How do I install MT5?"
2. "Where do I find Volatility 25 Index?"
3. "Why isn't the EA trading?" (smiley face / Algo Trading off)
4. "What does this error mean?" (point them to USER_GUIDE.md troubleshooting)
5. "Can I run it on V75?" (no, scanner says no)
6. "Can I run it 24/7?" (yes, but needs VPS or PC always on)
7. "What VPS do you recommend?"
8. "How much money do I need to start?"
9. "Why did I lose money on a trade?" (R:R = 1:1.875, losses are expected)
10. "Can I run it on my phone?"  (no, phone MT5 doesn't run EAs)
11. "What's the win rate?"
12. "Can I change settings?" (yes, but they're optimised — caveat emptor)
13. "How do I update?" (provide auto-update or notify by email)
14. "When are trades placed?" (UTC session boundaries)
15. "Why is my time different from your time?" (timezone, broker time)
16. "What's a 'tick'?"
17. "What's R:R?"
18. "It made one trade then stopped — why?" (probably daily stop)
19. "Can I run multiple symbols?" (yes, separate charts)
20. "Will this work on a prop firm account?" (depends on prop firm rules)

---

## 5. VPS recommendation (you'll get asked)

The EA needs MT5 running 24/7. Options to recommend:
- **ForexVPS.net** — purpose-built for MT5, ~$25/mo, low latency
- **CommercialNetwork.net** — cheap Windows VPS, ~$5/mo
- **Contabo VPS** — generic Windows VPS, ~$7/mo
- **Self-hosted** — leave PC on with sleep disabled (free but unreliable)

Make it clear: without a VPS or always-on PC, the EA stops trading whenever the machine sleeps/disconnects.

---

## 6. Marketing materials

Things to prepare:
- **Landing page** with the strategy explanation in plain English
- **Backtest results graphic** — the monthly breakdown table from STRATEGY_REPORT.md
- **Demo account proof** — 2 weeks of demo trading screenshots
- **Honest comparison** — show losing days too, not just wins
- **Pricing page** — one-time vs subscription, refund policy

Suggested pricing (industry comparable for synthetic-index EAs):
- $97–$197 one-time (basic license, 1 account)
- $30–$50/month subscription (always-current version, includes support)
- $497 lifetime, unlimited accounts (for serious traders)

---

## 7. Refund policy

Standard for trading products:
- **No refunds** once the EA has been used to place live trades (auditable via account history)
- **7-day money-back if not run live** (only opened the file)
- **Free replacement** if the broker changes spec and the EA breaks (you fix and re-release)

State this prominently — beginners often expect refunds when they lose money trading, which is not what a software refund covers.

---

## 8. What you should NOT promise

Even if true at the moment of the sale:
- ❌ "This will make you money"
- ❌ "I'll fix it personally if it breaks"  (you might be busy)
- ❌ "Works on any broker"  (it's tuned for Deriv V25)
- ❌ "Set and forget"  (it still needs monitoring)
- ❌ "Works on every Deriv symbol"  (only V25 confirmed; others need testing)

Set the bar low; over-deliver in support.

---

## 9. Update / version management

When you ship v1.00 and later improve to v1.01:
- Keep a `VERSION_HISTORY.md` showing what changed
- Email previous buyers with the update (if subscription model, push it automatically)
- Don't break inputs without a version bump — old users' settings should keep working

---

## 10. Things you DON'T sell — the source

Never bundle:
- Source `.mq5` files (`OpenCloseEA.mq5`, `ICTSessionsEA.mq5`)
- `PatternScanner.py` (your research tool)
- This documentation suite (CHANGELOG, USER_GUIDE, STRATEGY_REPORT, SELLER_CHECKLIST)
- The `scanner_results.csv` (your raw research data)

If you do, buyers can:
- Modify the code and resell as their own
- Run the scanner themselves and replicate your research
- Read your internal notes (e.g., known bugs in CHANGELOG)

Build a **buyer-facing distribution** with only:
- `ICTSessionsEA.ex5` (compiled, account-locked)
- `SessionOCLevels.ex5` (compiled)
- `Quick Start Guide.pdf` (1-page install)
- `User Manual.pdf` (10-page how to use)
- `FAQ.pdf`
- `Risk Disclaimer.pdf`

---

## Pre-launch checklist

Before announcing v1.0:

- [ ] EA runs on demo for 4+ weeks without crashes
- [ ] Live demo expectancy is positive (even at 50% of backtest)
- [ ] Account-locked license implemented
- [ ] All 4 PDFs ready
- [ ] 10-min installation video recorded
- [ ] Support channel (Telegram/Discord) set up
- [ ] Landing page live
- [ ] Payment integration tested (Stripe, Paystack, etc.)
- [ ] Refund policy written and on landing page
- [ ] Risk disclaimer on every page
- [ ] At least 3 beta testers have installed successfully without you helping
- [ ] You can answer all 20 FAQ questions from memory

---

_Remember: the EA is the easy part. The hard part is supporting buyers who don't know what a candle is._
