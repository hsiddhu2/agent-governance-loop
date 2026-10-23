"""The support tool returns one ticket as stored, and nothing else."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HANDLER = Path(__file__).resolve().parent.parent / "tools/support/handler.py"


class FakeDynamo:
    def __init__(self, items: dict):
        self.items = items
        self.calls = []

    def get_item(self, TableName, Key):
        self.calls.append((TableName, Key["pk"]["S"]))
        item = self.items.get((TableName, Key["pk"]["S"]))
        return {"Item": item} if item else {}


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.setenv("TABLE_PREFIX", "agl-tickets-")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    spec = importlib.util.spec_from_file_location("support_handler", HANDLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ddb = FakeDynamo({("agl-tickets-production", "ticket#1"): {
        "pk": {"S": "ticket#1"}, "claim_id": {"S": "claim#4"}, "status": {"S": "open"},
        "subject": {"S": "Where is my claim?"}, "body": {"S": "Hello."}, "env": {"S": "production"},
    }})
    yield module
    sys.modules.pop("support_handler", None)


def context(tool: str):
    return SimpleNamespace(aws_request_id="r-1",
                           client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": tool}))


def test_get_ticket_returns_the_schema_fields_only(handler):
    out = handler.handler({"environment": "production", "ticket_id": "ticket#1"}, context("x___get_ticket"))
    assert out == {"ticket_id": "ticket#1", "claim_id": "claim#4", "status": "open",
                   "subject": "Where is my claim?", "body": "Hello."}
    assert handler.ddb.calls == [("agl-tickets-production", "ticket#1")]


def test_unknown_ticket_is_an_error(handler):
    with pytest.raises(ValueError):
        handler.handler({"environment": "production", "ticket_id": "ticket#9"}, context("x___get_ticket"))


def test_unknown_tool_is_refused(handler):
    with pytest.raises(ValueError):
        handler.handler({}, context("x___purge_claims"))
