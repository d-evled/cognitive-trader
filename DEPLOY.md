# Deploying the read-only demo

The **Dashboard** and **Trade Log** pages are pure SQLite — they render from a
committed snapshot ([`demo/cognitive_trader.db`](demo/cognitive_trader.db)) with
no API keys and no vector index. That makes them safe to host as a public,
read-only demo on **Streamlit Community Cloud** (free).

The live trading loop (Alpaca), LLM vetting, and the Chat page's retrieval index
stay **local** — they aren't part of the deploy.

## How the demo data works

`data/` is gitignored (it's derived and machine-specific), so a fresh clone or a
cloud deploy has no live DB. The app handles this: `src/app/ui.resolve_db_path`
falls back to the committed `demo/` snapshot when `data/cognitive_trader.db` is
absent, and shows a "📦 Demo mode" banner so visitors know the numbers are a
snapshot. Once you run the pipeline locally, the live DB takes over automatically.

To refresh the snapshot after accruing more paper history locally:

```bash
cp data/cognitive_trader.db demo/cognitive_trader.db
git add demo/cognitive_trader.db && git commit -m "Refresh demo snapshot"
```

## Streamlit Community Cloud — steps

1. **Push to a public GitHub repo.** From this project directory:
   ```bash
   git remote add origin https://github.com/<you>/cognitive-trader.git
   git push -u origin main
   ```
   (`.env`, `data/`, and `logs/` are gitignored and will not be pushed — verify
   with `git status` before pushing.)

2. **Create the app** at [share.streamlit.io](https://share.streamlit.io) →
   *New app* → pick your repo/branch.
   - **Main file path:** `src/app/streamlit_app.py`
   - Community Cloud auto-installs from the root `requirements.txt` — which is
     deliberately **lean** (streamlit/altair/pandas/pyyaml/dotenv only). The heavy
     ML/RAG stack is in `requirements-full.txt` and is **not** installed on Cloud
     (torch/tokenizers don't build on Cloud's newer Python, and the demo pages
     don't need them).
   - **Python version:** if the build fails compiling a native wheel, set the
     Python version to **3.12 or 3.13** under *Advanced settings* (Cloud may
     otherwise pick a version too new for some wheels).

3. **(Optional) Enable the Chat page's answer generation** — add your Anthropic
   key under *App → Settings → Secrets*:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```
   See [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example).
   Chat *retrieval* still needs the local Chroma index, so on cloud the Chat page
   shows a "run locally" notice by design — the demo lives in Dashboard + Trade
   Log.

## Notes / watch-outs

- **Two requirements files.** Root `requirements.txt` is the lean deploy set (the
  two SQLite pages need only `streamlit`, `altair`, `pandas`, `pyyaml`, and
  `python-dotenv`). `requirements-full.txt` adds the RAG/LLM/broker stack for
  local development. Cloud uses the lean file automatically — no torch, no Rust
  build, fast deploys.
- **Never commit secrets.** Cloud secrets go in the Streamlit Secrets UI (which
  populates `st.secrets` / env), not in the repo.
- **The demo is illustrative, not a track record** — it's an early paper account.
  Backtest results are reported separately in the [README](README.md#honest-results).
