# Cognitive Trader — Handoff / Continuation Notes

Paste this into Claude Code to pick up where the design + Week 1 build left off.

## What this project is
A retrieval-augmented (RAG) **swing-trading assistant** for US stocks on daily bars (holds of days to weeks). Deterministic quantitative **rules propose** candidate trades; an **LLM vets** each one using retrieved evidence (your trade journal, similar historic setups, news) and returns approve/reject + position size + written reasoning with citations. Trades run on an **Alpaca paper account**. A Streamlit app gives a dashboard + chat over the knowledge base.

Dual purpose: job-search portfolio piece **and** a real decision-support tool. Framing everywhere is "decision support with retrieval-grounded reasoning," NOT "profitable bot." Not financial advice.

## Locked-in decisions
- US stocks, **daily bars**, long-only v1. Swing style.
- **Rules propose, AI disposes.** LLM value-add is a single ablatable stage.
- **Risk lives in code, not prompts** — gates enforce caps/stops before the LLM; LLM can only size *below* the cap.
- **SQLite = source of truth; Chroma = derived index** (rebuildable).
- Setup "cards" (templated text) make price patterns embeddable + human-readable + citable.
- Citations validated in code (hallucinated cites → auto-reject). Prompts versioned.
- Stack (all free except LLM): Python, yfinance, SQLite, Chroma, local sentence-transformers embeddings, **Claude API** for vetting (~$5–15/mo during dev only), Streamlit, Streamlit Community Cloud for the hosted demo.
- Timeline: 6-week sprint. Beginner-ish coder — keep scaffolding + explanatory comments.

Full design in `ARCHITECTURE.md`; week-by-week in `BUILD_PLAN.md`.

## What's built and working (Week 1 ✅, Week 2 code ✅)
Verified on real data: backfilled ~751 rows/ticker (~3y), `run_daily.py --dry-run` fired a real trend_pullback on AAPL and passed gates. All 39 tests pass. Git repo initialized; Week 2 built on branch `week-2-paper-trading`.

```
config.yaml                 # universe (31 tickers w/ sectors), indicator params, rules, risk caps
src/config.py               # loads config; CT_DB_OVERRIDE env for dev DBs
src/data/db.py              # SQLite schema (6 tables) + trade lifecycle helpers (record/open/close trade, trading-day calendar via SPY)
src/data/ingest.py          # yfinance backfill + idempotent daily_update
src/signals/indicators.py   # hand-rolled SMA/RSI/ATR/rolling_high + enrich()
src/signals/rules.py        # Candidate dataclass; 3 rules; scan()
src/risk/gates.py           # PortfolioState, apply_gates(): rejects + computes max size
src/broker/alpaca_client.py # AlpacaBroker (paper-only): GTC bracket orders, positions, exit fills; pure helpers shares_for/exit_reason
src/broker/reconcile.py     # syncs DB with broker: records exits + P&L + exit journal, syncs fill prices, enforces 20-day time stop
src/journal/journaler.py    # entry/exit journal templates (embed-ready prose) + writes (embedded=0 for Week 3 sync)
scripts/backfill.py         # one-time history pull
scripts/run_daily.py        # ingest→reconcile→rules→gates→execute; dry-run default, --execute places paper orders
scripts/dev_seed.py         # DEV ONLY synthetic data (use --db /tmp/x.db)
tests/                      # 39 tests incl. broker logic, trade lifecycle, journal, reconcile (FakeBroker, offline)
```

Run it:
```
pip install -r requirements.txt
python scripts/backfill.py
python scripts/run_daily.py            # dry run (works without Alpaca keys)
python scripts/run_daily.py --execute  # real paper orders (needs .env)
pytest -q
```

## Week 2 ✅ (live on paper) and Week 3 ✅ (RAG core) — done
**Week 2 live check passed:** Alpaca paper account connected (.env), `run_daily.py --execute` placed a real GTC bracket on AAPL (31 sh, id in DB trade 1), visible in the Alpaca dashboard, entry journal written. Nightly automation is installed as a launchd job (`com.cognitivetrader.daily`, 2pm PT weekdays) — see below.

**Week 3 done-when verified:** `scripts/rebuild_index.py` embedded **16,337 setup cards** (+1 journal entry) into Chroma; `scripts/show_bundle.py --no-fetch` prints today's AAPL bundle — 10 date-filtered similar setups with forward-return base rates (median fwd_10d +2.99%, 70% positive) and the same-rule journal entry. No-lookahead filter confirmed on real data.

New in Week 3:
```
src/rag/setup_cards.py   # card text template + forward returns + build_cards()
src/rag/embedder.py      # KnowledgeBase: local MiniLM embeddings + Chroma; date_ord no-lookahead filter
src/rag/retriever.py     # build_retrieval_bundle() + forward-return base-rate stats
src/rag/sync.py          # embed journal_entries where embedded=0 (idempotent)
scripts/rebuild_index.py # regenerate Chroma from SQLite (Chroma is derived; run anytime)
scripts/show_bundle.py   # print the evidence bundle for today's candidate(s)
```
Run: `python scripts/rebuild_index.py` then `python scripts/show_bundle.py`.

### ⚠️ Environment gotchas (bit us in Week 3)
- **Dep pins matter.** anaconda base has `torch 2.2.2`; newer sentence-transformers/transformers need torch≥2.4 and a huggingface_hub that dropped `HfFolder`. requirements.txt pins `sentence-transformers==2.7.0 / transformers==4.41.2 / huggingface_hub==0.23.4 / tokenizers<0.20`. Bump these only together with a torch upgrade.
- **launchd + ~/Desktop = TCC wall.** The nightly job fails ("Operation not permitted", exit 126) until Full Disk Access is granted to `/bin/bash` AND `/Users/samxie/anaconda3/bin/python3.11` (System Settings → Privacy & Security → Full Disk Access). Once granted: `launchctl unload/load ~/Library/LaunchAgents/com.cognitivetrader.daily.plist`, then `launchctl kickstart -k gui/$(id -u)/com.cognitivetrader.daily` to test. Logs in `logs/nightly.log`. **Do not switch Python interpreters** (e.g. a venv) without re-granting FDA to the new binary.

Week 2 design notes still in force:
- Bracket orders are **GTC** (DAY legs would expire end of entry day, leaving swing holds unprotected).
- Rules-only mode records a stand-in `decisions` row (`model='rules-only'`) so `signals→decisions→trades` stays traceable; Week 4 swaps in real LLM verdicts (same shape).
- `entry_price` is the signal close at submit; reconcile adopts the broker's actual `avg_entry_price` once the position appears.
- Reconcile: time-stop market-closes ≥20-trading-day positions (SPY dates = calendar); skips tickers with a pending entry order; never guesses on a vanished position with no exit fill.

## Week 4 ✅ (LLM vetting + backtester) — code done
The AI is in the loop. Built and tested (99 tests total):
```
src/llm/contracts.py   # parse/validate model JSON; citation check (hallucinated cite → auto-reject); size clamp to cap; retry-then-error
src/llm/vetter.py      # the vetting call (injected client); build_user_content(bundle); output_config JSON-schema; retry-once
src/llm/cache.py       # ResponseCache keyed on (candidate_hash, prompt_version); candidate_hash()
src/llm/pipeline.py    # build_vetter(cfg, client) + make_vet_fn(kb, vetter) — wires retriever+vetter
prompts/vet_v1.md      # the versioned vetting prompt (prompt_version = file stem "vet_v1")
src/backtest/engine.py # simulate_trade() bar-by-bar stop/target/time-stop; summary_stats() (win rate, avg W/L, return, maxDD, per-rule)
src/backtest/runner.py # run_backtest(): day-by-day replay through rules→gates→vet→sim fills; vet_fn=None is rules-only baseline
scripts/backtest.py    # rules-only vs rules+LLM side-by-side report; --llm adds the Haiku column
```
Also: `run_daily.py --vet` inserts vetting between gates and execute (records verdict/size/reasoning/citations/confidence/prompt_version per decision, rejects included; submits only approved trades at the vetted size). config `llm:` section (daily_model=claude-sonnet-5, backtest_model=claude-haiku-4-5, prompt_path, cache_path).

**Verified free/offline:** rules-only backtest on real data ran end-to-end — last year: **98 trades, 51% win rate, +10.9% return, 4.5% max drawdown** (breakout 67@52%, oversold 9@56%, trend_pullback 22@45%). This is the baseline the LLM must beat. All vetting/contract/cache/backtest logic is unit-tested with fakes (no API calls).

### ⚠️ Remaining for Week 4's done-when (needs your Anthropic key)
Add `ANTHROPIC_API_KEY` to `.env` (see `.env.example`; ~$5–15/mo). Then:
- **Backtest comparison:** `python scripts/backtest.py --llm` → side-by-side rules-only vs rules+LLM. (First run embeds/caches per-candidate Haiku calls; reruns are free via the cache.)
- **Nightly vetting:** `python scripts/run_daily.py --execute --vet` → each candidate is vetted, reasoning/citations stored in `decisions`, only approved trades placed. To make the launchd job vet nightly, add `--vet` to the run line in `scripts/nightly.sh`.

Week 4 design notes:
- **Model choice** (ARCHITECTURE §3): Sonnet 5 daily (low volume, pennies), Haiku 4.5 for backtests (thousands of calls). Both in config; the request shape (model id + `output_config` JSON-schema) follows the current `claude-api` skill docs — read that skill before changing model/params.
- **Safety in code, not prompt:** citations validated against the bundle (hallucination → auto-reject), size clamped to the gate cap, malformed output → `verdict:"error"` (never trades). The LLM can only reject or size *below* the cap.
- **No lookahead in backtests:** each day's rules see only bars ≤ that day; retrieval is date-filtered; `simulate_trade` uses future bars *only* to resolve an already-committed trade's outcome.
- `MAX_TOKENS=4096` for the vetter — Sonnet 5 runs adaptive thinking by default (shares the budget); a tight cap would truncate the JSON.

## Week 5 ✅ (Streamlit app + news) — done
Three-page app, verified in a real browser (all pages load, retrieval works, no errors). 110 tests.
```
.streamlit/config.toml        # dark "quant desk" theme (amber on near-black)
src/app/ui.py                 # shared chrome: theme CSS (Fraunces + JetBrains Mono), get_conn (routes through db.get_conn → migrations), render_bundle()
src/app/queries.py            # data layer (tested): open_positions (unrealized P&L), recent_decisions (+parsed bundle), equity_curve, trade_log
src/app/streamlit_app.py      # Dashboard: metrics, equity curve, open positions, decisions feed — each expands to the stored evidence bundle (the money shot)
src/app/pages/1_Trade_Log.py  # filterable trade table + per-rule stats
src/app/pages/2_Chat.py       # RAG Q&A: retrieval always works; answer generation needs ANTHROPIC_API_KEY (gated)
src/data/news.py              # fetch_news (yfinance, defensive) + store_news_items (dedup by URL) + sync_news
scripts/ingest_news.py        # fetch → store → embed into the news collection
```
Run the app: `streamlit run src/app/streamlit_app.py` (or via `.claude/launch.json`).

New this week:
- **Bundle storage** — `decisions.bundle_json` (added via an idempotent migration in `db.get_conn`); `run_daily --vet` stores `bundle_to_json(bundle)` per decision, so the dashboard renders exactly what the model saw. Rules-only decisions have no bundle (shown as such).
- **News in the bundle** — `KnowledgeBase.add_news/query_news` (ticker + date-filtered, no lookahead); `retriever.build_retrieval_bundle` includes news when the store supports `query_news`. **Verified live:** ingested 155 headlines, 129 stored + embedded.
- `rebuild_index.py` now also re-embeds news.

Notes:
- The app's `get_conn` routes through `db.get_conn` so schema migrations apply to an old DB file (the bundle_json column). Streamlit caches imported modules — **restart the server after editing `src/app/*.py`**, a rerun isn't enough.
- Chat/dashboard need the Chroma index built (`scripts/rebuild_index.py`); the dashboard itself only needs SQLite.
- Still no `ANTHROPIC_API_KEY` set — the Chat answer and `--vet`/`--llm` remain gated on it. Dashboard, trade log, chat *retrieval*, and news all work without it.

## Week 6 ✅ — polish, deploy, package
- **`README.md`** — pitch, the 7 design decisions as a table, the honest results table (rules-only 98/51%/+10.9%/4.5% maxDD), an ASCII architecture flow, quickstart, project layout, and a prominent disclaimer.
- **Deploy-ready for Streamlit Community Cloud (read-only demo):**
  - `demo/cognitive_trader.db` — committed snapshot (2 MB) so a fresh clone / cloud deploy isn't blank (`data/` is gitignored).
  - `src/app/ui.resolve_db_path` — falls back to the demo snapshot when the live DB is absent; `demo_banner()` shows a "📦 Demo mode" notice. Live DB takes over automatically once you run the pipeline locally. **4 new tests** (`tests/test_app_demo.py`), TDD.
  - Chat page degrades gracefully (try/except around the index load) so it shows a "run locally" notice on cloud instead of a stack trace. Dashboard + Trade Log are the SQLite-only demo surface — no keys, no torch.
  - `DEPLOY.md` — exact Community Cloud steps, snapshot-refresh command, secrets flow. `.streamlit/secrets.toml.example` added; `.streamlit/secrets.toml` gitignored.
- **`DEMO.md`** — a timed 3–5 min video script following one candidate: signal → gates → evidence bundle → vet+cite → order → journal → honest measurement. (Recording is the user's to do.)
- Full suite green: **114 passed**.
- Interview prep: rehearse the 7 design decisions (ARCHITECTURE §11 / README table).

## SHIPPED — v1.0 is live 🚀
- **Repo:** https://github.com/d-evled/cognitive-trader (public; topics + `v1.0` release published).
- **Live demo:** https://cognitive-trader.streamlit.app/ — Dashboard + Trade Log render the committed snapshot in "📦 Demo mode"; Chat shows its "run locally" notice by design.
- **Two deploy bugs found + fixed during the Cloud rollout** (both documented in DEPLOY.md → "Deploy bugs we already hit"):
  1. **Python-3.14 wheel build failure** — Cloud built on a newer Python than local; the pinned `tokenizers` had no wheel and failed to compile. Fixed by splitting `requirements.txt` (lean deploy: streamlit/altair/pandas/pyyaml/dotenv) vs `requirements-full.txt` (RAG/LLM/broker + tests for local). The demo host never installs torch now.
  2. **Over-broad `.gitignore` hid `src/data/`** — the un-anchored `data/` pattern matched `src/data/` too, so the entire data-layer package (db/ingest/news) was never committed and the Cloud clone crashed with `No module named 'src.data.db'` (Dashboard/Trade Log only; Chat unaffected). Fixed by anchoring to `/data/` and `/logs/` and committing the package. **Lesson: anchor gitignore dir patterns with a leading slash.**
- **Optional polish left (all user-owned, none blocking):** record the demo video from `DEMO.md`; periodically refresh the snapshot (`cp data/cognitive_trader.db demo/cognitive_trader.db` + commit) so the equity curve/Trade Log fill in; add `ANTHROPIC_API_KEY` in the app's Streamlit Secrets to light up Chat answers on the live demo.

## Watch-outs

## Watch-outs
- yfinance columns come capitalized / sometimes MultiIndex — `ingest._normalize()` handles it.
- No lookahead in future backtests: retrieval must date-filter to data available at that date.
- Keep risk caps in `gates.py`, never in prompts.
