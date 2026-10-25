"""A claim or store that does not exist comes back as a message the caller can read.

A plain tool answers with an MCP error result. A screened tool answers in its declared shape,
because a screen withholds an error result.
"""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

HANDLER = Path(__file__).resolve().parents[2] / "tools/ops/handler.py"
NO_TABLE = {"Error": {"Code": "ResourceNotFoundException", "Message": "no table"}}


class FakeDynamo:
    def __init__(self, tables: set[str]):
        self.tables = tables

    def get_item(self, TableName, Key):
        if TableName not in self.tables:
            raise ClientError(NO_TABLE, "GetItem")
        return {}

    def describe_table(self, TableName):
        raise ClientError(NO_TABLE, "DescribeTable")


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.setenv("TABLE_PREFIX", "agl-claims-")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    spec = importlib.util.spec_from_file_location("ops_handler", HANDLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ddb = FakeDynamo({"agl-claims-staging"})
    yield module
    sys.modules.pop("ops_handler", None)


def context(tool: str):
    return SimpleNamespace(aws_request_id="r-1",
                           client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": tool}))


def error_text(out: dict) -> str:
    assert out["isError"] is True
    (item,) = out["content"]
    assert item["type"] == "text"
    return item["text"]


def test_a_missing_claim_names_the_id_and_its_format(handler):
    out = handler.handler({"environment": "staging", "claim_id": "0"}, context("x___get_claim"))
    assert error_text(out) == "No claim 0 in staging. Claim ids look like claim#12."


def test_a_missing_claim_record_keeps_the_screened_shape(handler):
    # get_claim_record is screened, so a not-found keeps the fields its screens read.
    out = handler.handler({"environment": "staging", "claim_id": "0"}, context("x___get_claim_record"))
    assert out == {"claim_id": "0", "status": "not_found", "policyholder": "Not found.",
                   "health": "Not found.", "error": "No claim 0 in staging. Claim ids look like claim#12."}


def test_a_missing_store_points_to_list_env(handler):
    out = handler.handler({"environment": "prod"}, context("x___get_claims_store"))
    assert error_text(out) == "No claims store for environment prod. Call list_env for the environments."


def test_an_unknown_tool_is_still_an_exception(handler):
    with pytest.raises(ValueError):
        handler.handler({}, context("x___drop_everything"))
