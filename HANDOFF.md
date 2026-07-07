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

## Next: Week 4 — LLM vetting + backtester
- `src/llm/contracts.py`: JSON schema validation, citation checking (every cited id must be in the bundle — hallucinated cite → auto-reject), size clamping to gate cap, retry-then-auto-reject.
- `src/llm/vetter.py` + `prompts/vet_v1.md`: the vetting call (Sonnet daily, Haiku for bulk backtests). Feed it `build_retrieval_bundle(candidate)`; log the decision with `prompt_version`. **Read the `claude-api` skill first — don't guess model ids/params.**
- `src/llm/cache.py`: response cache keyed on `(candidate_hash, prompt_version)` so backtest reruns are free.
- `scripts/backtest.py`: replay 1–2 yrs, rules-only vs rules+LLM (Haiku), simulated bracket fills, honoring stops/targets bar-by-bar; retrieval date-filtered (the no-lookahead machinery already exists).
- Wire vetting into `run_daily.py` between gates and execute (the insertion point is where rules-only currently auto-approves).
- Done when: backtest produces a side-by-side rules-only vs rules+LLM report, and the nightly loop stores reasoning per decision.

Then Week 5 = Streamlit + news, Week 6 = polish/deploy/video.

## Watch-outs
- yfinance columns come capitalized / sometimes MultiIndex — `ingest._normalize()` handles it.
- No lookahead in future backtests: retrieval must date-filter to data available at that date.
- Keep risk caps in `gates.py`, never in prompts.
