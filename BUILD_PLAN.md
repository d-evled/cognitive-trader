# Cognitive Trader — 6-Week Build Plan

Companion to `ARCHITECTURE.md`. Each week has a goal, concrete tasks, a **done-when** check you can verify yourself, and a note on what you're learning. Rule of the sprint: **if a week runs over, cut from the bottom of that week's list, never from the done-when check.**

## Week 1 — Data foundation + rules engine

**Goal:** prices flowing into SQLite daily, rules firing on real data.

- Set up repo, virtualenv, `config.yaml`, and the SQLite schema from ARCHITECTURE §4
- `backfill.py`: 3 years of daily bars for a ~30-ticker universe (liquid large caps + a few ETFs) via yfinance
- `ingest.py`: idempotent daily update (safe to run twice)
- `indicators.py`: SMA, RSI, ATR, rolling highs — write these yourself before reaching for a library; it's the fastest way to learn what they mean
- `rules.py`: the three rules as pure functions, with unit tests on hand-built fixtures
- `gates.py`: risk checks, with tests

**Done when:** `python scripts/run_daily.py --dry-run` prints today's candidate trades with indicator context, and `pytest` passes.

*Learning focus: pandas, SQLite, what the indicators actually measure.*

## Week 2 — Paper trading loop + journal

**Goal:** end-to-end loop trading on Alpaca paper — no AI yet.

- Alpaca paper account + `alpaca_client.py`: submit bracket orders (entry/stop/target), poll fills, reconcile positions
- Wire `run_daily.py`: ingest → rules → gates → execute (rules-only mode)
- `journaler.py`: auto-write entry/exit journal rows; template the exit post-mortem
- Time-stop enforcement (close positions > 20 trading days old)
- Start running the loop for real each evening — from now on the system is *live on paper*, accumulating journal entries for the RAG layer

**Done when:** a candidate becomes a real paper order visible in the Alpaca dashboard, and a manually-closed position produces an exit journal entry.

*Learning focus: broker APIs, order types, why bracket orders (never hold a position without a stop).*

## Week 3 — The RAG core

**Goal:** knowledge base built; retrieval working.

- `embedder.py`: local sentence-transformers wrapper; Chroma persistent client
- `setup_cards.py`: card template from ARCHITECTURE §5.2; backfill ~3 yrs × 30 tickers with forward-return metadata
- Journal sync: embed rows where `embedded = 0`
- `retriever.py`: `build_retrieval_bundle(candidate)` with date filtering (the no-lookahead guarantee)
- `rebuild_index.py`
- Sanity-check retrieval quality by hand: do the nearest setup cards *look* similar to you? Tune the card template until they do — this is the highest-leverage tuning in the project

**Done when:** given today's candidate, you can print the bundle: 4 journal entries, 10 similar setups with forward-return stats, all correctly date-filtered.

*Learning focus: embeddings, vector search, metadata filtering — the heart of RAG.*

## Week 4 — LLM vetting + backtester

**Goal:** the AI is in the loop; the headline experiment runs.

- `contracts.py`: JSON schema validation, citation checking, size clamping, retry-then-auto-reject
- `vetter.py` + `prompts/vet_v1.md`: vetting call (Sonnet daily, Haiku bulk), decisions logged with prompt version
- `cache.py`: response cache keyed on `(candidate_hash, prompt_version)`
- `backtest.py`: replay 1–2 years, rules-only vs rules+LLM (Haiku), simulated bracket fills
- Report: equity curves, win rate, drawdown, per-rule stats

**Done when:** the backtest produces a side-by-side comparison report, and the nightly loop now includes vetting with reasoning stored per decision.

*Learning focus: prompt engineering against a strict contract, evaluation hygiene, reading a backtest skeptically.*

## Week 5 — Streamlit app + news

**Goal:** the demo surface.

- Dashboard page: equity curve, open positions, decisions feed with expandable evidence bundles
- Trade log page: filterable, joined to decisions and journal
- Chat page: RAG Q&A over all collections (`prompts/chat_v1.md`)
- News ingest: yfinance ticker news → `news_items` → `news` collection; add to bundle
- **Cut line if behind schedule: news first, then chat page. The dashboard is non-negotiable.**

**Done when:** you can open the app, click a decision, and show someone exactly what the AI saw and why it decided — in under 30 seconds.

*Learning focus: Streamlit, presenting evidence-based reasoning in a UI.*

## Week 6 — Polish, deploy, package

**Goal:** portfolio-ready.

- README: what/why, architecture diagram, honest backtest results, screenshots, disclaimers
- Deploy to Streamlit Community Cloud (read-only demo mode: dashboard + chat on a snapshot DB; the trading loop stays local)
- 3–5 min demo video: one candidate's full journey — signal → evidence → reasoning → order → journal
- Interview prep: rehearse the 7 design decisions in ARCHITECTURE §11; know the alternatives you rejected and why
- Tag `v1.0`

**Done when:** a stranger can go URL → README → video and understand the project in 10 minutes without you present.

## After the sprint

Keep the nightly loop running — the journal flywheel is the whole point, and "it's been paper trading for N weeks, here's what it learned" is a great interview line. Backlog, in rough order: trading-literature collection, LLM-assisted weekly journal review proposing rule tweaks, numeric k-NN setups comparison, richer news sources, live capital *only* after months of paper evidence and a hard think about position sizing.
