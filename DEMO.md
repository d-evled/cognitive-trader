# Demo video script (3–5 min)

Goal: a stranger watches this and understands *what the system does and why it's
built this way* — following **one candidate's full journey**: signal → evidence →
reasoning → order → journal. Screen-record with the app running locally (so Chat
and `--vet` work) plus a terminal.

Keep it to ~4 minutes. Times are targets, not gospel.

---

### 0:00 — Hook (20s)
> "Most 'AI trading bots' are a prompt wrapped around a price feed. Cognitive
> Trader is the opposite: deterministic rules find the opportunities, and the
> language model's only job is to *vet* them — grounded in what actually happened
> to similar setups in the past. Let me show you one trade end to end."

Show the **Dashboard** (`streamlit run src/app/streamlit_app.py`). Point at the
equity curve, open positions, and the decisions feed. Say the disclaimer out loud:
*"This is a paper account — decision support, not financial advice."*

### 0:20 — The signal (40s)
Switch to a terminal. Run the daily scan:
```bash
python scripts/run_daily.py --vet
```
While it runs, explain: *"Three classic swing rules scan 30 large caps —
trend-pullback, breakout, oversold reversion. They emit candidates with a fixed
entry, stop, and target. This is deterministic and fully testable — no model
involved yet."* Pick one candidate to follow (say the ticker aloud).

### 1:00 — Risk gates (30s)
> "Before the model ever sees it, the candidate passes through the risk gates —
> in *code*, not the prompt. Max 10% per position, max 2% risk per trade, sector
> and count caps. The model can only ever size *below* the cap or reject. This is
> the 'where not to trust an LLM' decision."

Show `src/risk/gates.py` briefly — the caps are right there in `config.yaml`.

### 1:30 — The evidence bundle (60s) ← the core
> "Here's the RAG part. For this candidate we retrieve the 10 most similar
> historical setups — and crucially, only ones dated *before* today, so there's no
> lookahead. From their forward returns we compute a base rate: 'median 10-day
> return, percent positive.' We add past journal notes on the same rule, and
> recent news."

Run (prints the bundle for each of today's candidates):
```bash
python scripts/show_bundle.py
```
Scroll to your candidate's bundle. Emphasize the base-rate line and the date
cutoff. *"This is the case file the model reads — and exactly what gets stored so
we can show it later."*

### 2:30 — The model vets, and cites (45s)
Back to the **Dashboard** → expand the new decision. Show the reasoning, the
verdict (approve/reject), and the **cited evidence IDs**.
> "The model returns a strict JSON verdict with citations. And here's the honesty
> mechanism: every citation is validated *in code* against the actual retrieved
> IDs. If it cites evidence that wasn't there, the decision is auto-rejected. No
> trusting the model's word."

### 3:15 — Order + the flywheel (30s)
> "Approved trades become GTC bracket orders on Alpaca paper — entry, stop, and
> target in one atomic order, so a swing hold is never left unprotected. When a
> trade closes, it's written back as a journal entry and re-embedded — so the next
> similar setup retrieves the system's *own* past experience. The judgment
> compounds."

### 3:45 — Honesty / measurement (30s)
Show `scripts/backtest.py` output or the README results table.
> "Because the model is a single ablatable stage, I can backtest with it on and
> off and measure exactly what it adds. Rules-only baseline: 98 trades, 51% win
> rate, +10.9%, 4.5% max drawdown over the last year. The no-lookahead guarantee
> is what makes that number trustworthy instead of self-deception."

### 4:15 — Close (15s)
> "SQLite is the source of truth, the vector store is a rebuildable index, risk is
> in code, and every decision shows its evidence. That's Cognitive Trader —
> retrieval-grounded decision support you can actually audit. Code and README are
> linked below."

---

**Recording tips**
- Have the app already loaded and one candidate in mind before you hit record.
- If `--vet` is slow, pre-run it and narrate over the stored decision.
- Zoom the terminal font; the bundle and the citation IDs need to be legible.
- End on the expanded decision card — it's the single most memorable frame.
