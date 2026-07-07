# Cognitive Trader

**A retrieval-augmented decision-support system for swing trading US equities.**
It doesn't predict prices. It builds a *case* for each trade — grounding a language
model's judgment in the empirical track record of similar past setups — and shows
you exactly what evidence it saw.

> ⚠️ **Not financial advice.** This is a portfolio/learning project. It runs on a
> **paper** brokerage account and has never traded real money. Most short-horizon
> retail traders lose money. See [Disclaimer](#disclaimer).

---

## The one-sentence pitch

Deterministic rules scan ~30 large-cap stocks for classic swing setups; for each
candidate, the system retrieves the *k* most similar historical setups and past
trade-journal notes, computes their forward-return base rates, and asks Claude to
**vet** the trade — approve (sized under a hard risk cap) or reject — citing the
specific evidence it used. Risk limits are enforced in code, never in the prompt.

**"Rules propose, AI disposes."** The rules find opportunities; the LLM is a
judgment layer you can switch off to measure exactly what it adds.

---

## Why this is interesting (the design decisions)

Most "AI trading bot" projects are a prompt wrapped around a price feed. The
engineering here is in the parts that make the judgment *honest and measurable*:

| Decision | Why it matters |
|---|---|
| **Rules propose, AI disposes** | LLM value-add is isolated as a single ablatable stage. Run the backtest with and without it and the difference *is* the model's contribution — no hand-waving. |
| **Risk lives in code, not prompts** | The model physically cannot exceed the position cap, skip a stop, or over-concentrate a sector. It can only size *below* the cap or reject. Demonstrates knowing where **not** to trust an LLM. |
| **SQLite is truth, Chroma is a derived index** | The vector store is rebuildable from scratch at any time (`rebuild_index.py`). Eliminates the sync-drift class of bugs entirely. |
| **Text "setup cards" for similarity** | Market state is rendered into a templated natural-language snapshot — embeddable, human-readable, and *citable*. |
| **Citations validated in code** | Every claim the model cites is checked against the actual retrieved evidence. Hallucinated evidence → the decision is auto-rejected. Prompts are versioned so decision quality is trackable over time. |
| **No lookahead in backtests** | Retrieval is date-filtered (via an integer `date_ord` cutoff) so a candidate on day *T* can only ever see cards dated ≤ *T*. This is the subtle bug most naive backtests have. |
| **The journal is a flywheel** | Every closed trade is written back as a journal entry and re-embedded, so future retrievals include the system's own past experience. Judgment compounds with use. |

---

## Honest results

Backtested over the last ~year on the 30-name universe, daily bars:

| Mode | Trades | Win rate | Total return | Max drawdown |
|---|---|---|---|---|
| **Rules only** (baseline) | 98 | 51% | +10.9% | 4.5% |

The rules-only baseline is the number to beat. The **rules + LLM** comparison
(`scripts/backtest.py --llm`) runs the same replay with Claude vetting each
candidate; whether the model's selectivity actually improves risk-adjusted return
is exactly the question this architecture is built to answer — and to answer
*without fooling itself*, which is why the no-lookahead guarantee matters. Numbers
will be refreshed here as the paper account accrues live history.

This is decision support with a transparent evidence trail — **not** a claim of
profitability.

---

## How it works

```
                 daily bars (yfinance)
                         │
                         ▼
   ┌──────────────┐   rules scan   ┌───────────────┐
   │  SQLite       │──────────────▶│  candidates    │   deterministic setups:
   │  (source of   │               │  (rule + entry │   trend-pullback,
   │   truth)      │               │   /stop/target)│   breakout, oversold
   └──────┬───────┘               └───────┬────────┘
          │ derives                        │
          ▼                                ▼
   ┌──────────────┐   retrieve k    ┌───────────────┐
   │  Chroma       │◀──────────────▶│  evidence      │   similar past setups +
   │  (vector index│  (date-filtered)│  bundle        │   their forward-return
   │   of setup     │                │                │   base rates + journal
   │   cards +      │                └───────┬────────┘   notes + news
   │   journal +    │                        │
   │   news)        │                        ▼
   └──────────────┘                  ┌───────────────┐
                                     │  RISK GATES    │  caps / stops / sector
                                     │  (code)        │  limits — hard, pre-LLM
                                     └───────┬────────┘
                                             ▼
                                     ┌───────────────┐
                                     │  Claude vets   │  approve (size ≤ cap,
                                     │  + cites       │  with reasoning) or
                                     │  evidence      │  reject. Citations
                                     └───────┬────────┘  validated in code.
                                             ▼
                              GTC bracket order → Alpaca (paper)
                                             │
                                             ▼
                              reconcile fills → journal → re-embed  ⟳ flywheel
```

**Stack:** Python 3.11 · yfinance · SQLite · Chroma · sentence-transformers
(`all-MiniLM-L6-v2`, local/CPU) · Anthropic Claude (`claude-sonnet-5` daily,
`claude-haiku-4-5` for backtests) · alpaca-py (paper) · Streamlit + Altair ·
macOS launchd for the nightly loop.

Everything except the LLM calls runs **free and offline**: data, indicators,
rules, embeddings, retrieval, the dashboard, and the trade log all work with no
API key.

---

## The app

A three-page Streamlit dashboard (dark "quant desk" theme — Fraunces headings,
JetBrains Mono figures):

- **Dashboard** — equity curve, open positions with unrealized P&L, and a
  decisions feed where **each decision expands to show exactly what the model
  saw**: its reasoning, the evidence it cited, the base rates, and matching
  journal notes. Signal → evidence → reasoning in one click.
- **Trade Log** — every closed trade joined to its originating decision, with
  per-rule performance stats.
- **Chat** — ask the retrieval layer questions ("show me pullbacks in strong
  uptrends") and get real setup cards back, with an optional Claude-generated
  answer grounded in them.

```bash
streamlit run src/app/streamlit_app.py
```

---

## Quickstart

```bash
# 1. Install (Python 3.11; the RAG deps are pinned for torch 2.2 — see requirements.txt)
pip install -r requirements.txt

# 2. Configure keys (all optional — the system degrades gracefully without them)
cp .env.example .env
#   ALPACA_API_KEY / ALPACA_SECRET_KEY  → paper trading loop
#   ANTHROPIC_API_KEY                   → LLM vetting + chat answers

# 3. Build the data + index (free, no keys needed)
python scripts/backfill.py         # download daily history into SQLite
python scripts/rebuild_index.py    # embed setup cards + journal + news into Chroma

# 4. See it
streamlit run src/app/streamlit_app.py
```

**Daily loop** (paper trading, needs Alpaca keys):

```bash
python scripts/run_daily.py            # rules-only: scan, gate, place bracket orders
python scripts/run_daily.py --vet      # + LLM vetting (needs ANTHROPIC_API_KEY)
```

**Backtest** (measure the LLM's contribution):

```bash
python scripts/backtest.py             # rules-only baseline
python scripts/backtest.py --llm       # rules + LLM, side by side
```

All tunables (universe, indicator windows, rule thresholds, **risk caps**) live
in [`config.yaml`](config.yaml). No magic numbers in code.

---

## Project layout

```
src/
  data/       ingest (yfinance), SQLite schema + migrations, news
  signals/    indicators, deterministic rules → candidates
  risk/        gates.py — the hard risk limits (caps, stops, sector/ticker/count)
  rag/         setup cards, embedder (Chroma), retriever (evidence bundle), sync
  llm/         vetting contract, prompt runner, response cache, pipeline
  broker/      Alpaca paper client (GTC brackets), fill reconciliation
  backtest/    day-by-day replay engine + runner (no-lookahead)
  journal/     closed-trade → journal entry (the flywheel)
  app/         Streamlit dashboard, trade log, chat
scripts/       backfill, rebuild_index, run_daily, backtest, ingest_news, …
prompts/       versioned prompts (vet_v1.md, chat_v1.md)
config.yaml    everything tunable
```

Built with TDD throughout — 110 passing tests (`pytest`).

---

## Testing

```bash
pytest            # full suite
pytest -q         # quiet
```

Tests cover the risk gates, the no-lookahead retrieval guarantee, the LLM
contract (schema parsing, citation validation, size clamping), fill
reconciliation edge cases, and the backtest engine.

---

## Disclaimer

This software is for **educational and research purposes only**. It is **not**
investment advice, and nothing it produces is a recommendation to buy or sell any
security. It runs on a **paper** (simulated) brokerage account and has never
placed a real-money order. Trading involves substantial risk of loss; most
short-horizon retail traders lose money. Past performance — including any
backtest shown here — does not indicate future results. Use at your own risk. The
author accepts no liability for any decisions made using this software.
