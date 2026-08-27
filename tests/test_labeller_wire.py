import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from basis.sources import claude_labeller

"""
The labeller has never been run against the real API, and it will not be until
someone has a key. These tests stand a stub of the Messages API in front of the
real SDK so the whole path is exercised anyway: the SDK has to accept the
parameters, the wire body has to carry the schema and the model, and the
parsing and error branches have to behave.

What is left unproven afterwards is the model's answer, not the plumbing.
"""

LABEL = {
    "policy_action": "cut",
    "action_size_bps": -25,
    "dissent_count": 1,
    "dissent_directions": ["tighter"],
    "inflation_language": "easing",
    "labor_language": "moderating",
    "growth_language": "moderate",
    "forward_guidance": "data_dependent",
    "balance_sheet_mentioned": True,
    "risk_balance": "balanced",
    "evidence": [{"field": "policy_action", "quote": "decided to lower the target range"}],
}


def message(text: str, stop_reason: str = "end_turn", stop_details=None) -> dict:
    return {
        "id": "msg_stub",
        "type": "message",
        "role": "assistant",
        "model": claude_labeller.MODEL,
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "stop_details": stop_details,
        "usage": {"input_tokens": 1200, "output_tokens": 180},
    }


class Stub:
    def __init__(self, payload: dict):
        self.payload = payload
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("content-length", 0))
                outer.requests.append(json.loads(self.rfile.read(length)))
                body = json.dumps(outer.payload).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        return False

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def client(self):
        anthropic = pytest.importorskip("anthropic")
        return anthropic.Anthropic(api_key="stub-key", base_url=self.url, max_retries=0)


def test_the_sdk_accepts_the_request_and_the_answer_parses():
    with Stub(message(json.dumps(LABEL))) as stub:
        value = claude_labeller.label("a statement body", stub.client())

    assert value == LABEL


def test_the_wire_body_carries_the_model_effort_and_schema():
    with Stub(message(json.dumps(LABEL))) as stub:
        claude_labeller.label("a statement body", stub.client())
        sent = stub.requests[0]

    assert sent["model"] == claude_labeller.MODEL
    assert sent["output_config"]["effort"] == claude_labeller.EFFORT
    assert sent["output_config"]["format"]["schema"] == claude_labeller.SCHEMA


def test_the_document_reaches_the_prompt_intact():
    body = "Voting against this action was Michelle W. Bowman."

    with Stub(message(json.dumps(LABEL))) as stub:
        claude_labeller.label(body, stub.client())
        sent = stub.requests[0]

    assert body in sent["messages"][0]["content"]


def test_a_refusal_raises_rather_than_storing_an_empty_label():
    refusal = message("", "refusal", {"type": "refusal", "category": "cyber"})

    with Stub(refusal) as stub, pytest.raises(RuntimeError, match="declined"):
        claude_labeller.label("a statement body", stub.client())


def test_a_truncated_answer_raises_rather_than_parsing_half_of_it():
    truncated = message(json.dumps(LABEL)[:40], "max_tokens")

    with Stub(truncated) as stub, pytest.raises(RuntimeError, match="cut off"):
        claude_labeller.label("a statement body", stub.client())


def test_the_request_is_identical_for_the_same_document():
    with Stub(message(json.dumps(LABEL))) as stub:
        client = stub.client()
        claude_labeller.label("same body", client)
        claude_labeller.label("same body", client)

    assert stub.requests[0] == stub.requests[1]


def test_the_dry_run_shows_the_request_a_paid_run_would_send():
    body = "a statement body"
    dry = claude_labeller.request_params(body)

    with Stub(message(json.dumps(LABEL))) as stub:
        claude_labeller.label(body, stub.client())
        sent = stub.requests[0]

    for field in ("model", "max_tokens", "output_config", "messages"):
        assert sent[field] == dry[field]
