"""The read-only demo needs the app to fall back to a committed snapshot DB
when the live (gitignored) data/ directory is absent — e.g. a fresh clone or a
Streamlit Community Cloud deploy. `resolve_db_path` encodes that rule; the write
path (backfill, run_daily) never uses it, so it can't affect real data.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.app.ui import resolve_db_path

LIVE = "data/cognitive_trader.db"
DEMO = "demo/cognitive_trader.db"


class TestResolveDbPath:
    def test_uses_live_db_when_present(self):
        # Live DB exists → use it, not a demo, and don't flag demo mode.
        path, is_demo = resolve_db_path(LIVE, DEMO, exists=lambda p: p == LIVE)
        assert path == LIVE
        assert is_demo is False

    def test_falls_back_to_demo_when_live_missing(self):
        # Fresh clone / cloud deploy: no live DB, but the committed snapshot is
        # there → serve the demo so the app isn't blank, and say so.
        path, is_demo = resolve_db_path(LIVE, DEMO, exists=lambda p: p == DEMO)
        assert path == DEMO
        assert is_demo is True

    def test_prefers_live_over_demo_when_both_exist(self):
        path, is_demo = resolve_db_path(LIVE, DEMO, exists=lambda p: True)
        assert path == LIVE
        assert is_demo is False

    def test_returns_live_when_neither_exists(self):
        # Neither present: hand back the live path so db.get_conn creates a
        # fresh empty DB (normal first-run-before-backfill behavior), not demo.
        path, is_demo = resolve_db_path(LIVE, DEMO, exists=lambda p: False)
        assert path == LIVE
        assert is_demo is False
