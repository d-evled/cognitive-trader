"""Chat — free-form RAG Q&A over the knowledge base.

Same retrieval layer as the vetting stage, conversational prompt instead of
the strict contract. Retrieval always works (local, free); answer generation
uses Claude and needs ANTHROPIC_API_KEY — without it, the page still shows
the retrieved evidence so you can see what a question surfaces.
"""
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root on path

import streamlit as st

from src.app.ui import disclaimer, get_cfg, setup_page

setup_page("Chat", icon="💬")
cfg = get_cfg()

st.title("Chat over your knowledge base")
disclaimer()
st.caption("Ask about your trades or historical setups, e.g. *“What's my win "
           "rate on breakout trades?”* or *“Show setups like a pullback in a "
           "strong uptrend.”* Answers are grounded only in retrieved evidence.")


@st.cache_resource
def _kb():
    from src.rag.embedder import KnowledgeBase
    return KnowledgeBase(cfg["data"]["chroma_path"], cfg["rag"]["embedding_model"])


question = st.text_input("Your question")
if not question:
    st.stop()

kb = _kb()
today = date.today().isoformat()
setups = kb.query_setups(question, as_of_date=today, k=6)
journal = kb.search_journal(question, k=6)

# --- answer (needs the API key) ------------------------------------------
have_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
if not have_key:
    from dotenv import load_dotenv
    load_dotenv(Path(cfg["data"]["db_path"]).resolve().parents[1] / ".env")
    have_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

if have_key:
    import anthropic
    from src.config import REPO_ROOT
    prompt = (REPO_ROOT / cfg["llm"]["prompt_path"]).with_name("chat_v1.md").read_text()
    evidence = "SETUP CARDS:\n" + "\n".join(
        f"[{h.id}] {h.text}" for h in setups)
    evidence += "\n\nJOURNAL:\n" + ("\n".join(
        f"[{h.id}] {h.text}" for h in journal) or "(empty)")
    with st.spinner("Thinking…"):
        resp = anthropic.Anthropic().messages.create(
            model=cfg["llm"]["daily_model"], max_tokens=1024, system=prompt,
            messages=[{"role": "user", "content": f"{question}\n\nEVIDENCE:\n{evidence}"}])
        answer = next((b.text for b in resp.content
                       if getattr(b, "type", None) == "text"), "")
    st.markdown("### Answer")
    st.markdown(answer)
else:
    st.warning("Answer generation needs `ANTHROPIC_API_KEY` in `.env`. Showing "
               "the retrieved evidence below in the meantime.")

# --- retrieved evidence (always shown) -----------------------------------
st.markdown("### Retrieved evidence")
st.markdown("**Setup cards**")
for h in setups:
    st.markdown(f"<span class='ct-badge'>{h.id}</span>"
                f"<span class='ct-card-text'>{h.text}</span>",
                unsafe_allow_html=True)
st.markdown("**Journal**")
if not journal:
    st.markdown("<span class='ct-card-text'>(journal empty — fills as trades "
                "close)</span>", unsafe_allow_html=True)
for h in journal:
    st.markdown(f"<span class='ct-badge'>{h.id}</span>"
                f"<span class='ct-card-text'>{h.text}</span>",
                unsafe_allow_html=True)
