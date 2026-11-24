import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session", autouse=True)
def seeded_db():
    from scripts.seed_db import seed
    seed()


@pytest.fixture
def fake_llm(monkeypatch):
    from tests.fake_llm import FakeLLM
    import agents.nodes as nodes
    import baselines.single_prompt as sp
    monkeypatch.setattr(nodes, "get_llm", lambda: FakeLLM())
    monkeypatch.setattr(sp, "make_chat_model", lambda **kw: FakeLLM())
    monkeypatch.setattr(sp, "_llm", None)
    import eval.runner as runner
    monkeypatch.setattr(runner, "preflight", lambda: None)
    monkeypatch.setenv("LLM_CACHE", "0")
    yield


def _warehouse_up() -> bool:
    try:
        from assistant.config import warehouse_available
        return warehouse_available()
    except Exception:
        return False


requires_warehouse = pytest.mark.skipif(not _warehouse_up(),
                                        reason="Postgres claims warehouse not available (python -m warehouse.load)")
