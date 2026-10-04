"""Légende Claude : une option refusée (400) relance une requête simple ; les autres
erreurs donnent un message compréhensible."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("anthropic")

from clipbot import captions  # noqa: E402

OK = {"id": "msg_1", "type": "message", "role": "assistant", "model": "m",
      "stop_reason": "end_turn", "stop_sequence": None,
      "usage": {"input_tokens": 1, "output_tokens": 1},
      "content": [{"type": "text", "text": json.dumps({"hook": "Quelle action",
                                                        "hashtags": ["fyp"]})}]}


def serve(responses):
    """Mini API : renvoie les réponses (statut, corps) dans l'ordre, note les requêtes."""
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body)
            status, data = responses[min(len(seen), len(responses)) - 1]
            raw = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


def err(message):
    return {"type": "error", "error": {"type": "invalid_request_error", "message": message}}


@pytest.fixture
def api(monkeypatch):
    def start(responses):
        srv, seen = serve(responses)
        monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{srv.server_port}")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        return seen
    return start


def call():
    return captions.generate_caption(title="t", channel="Nico_La", transcript="", model="m")


def test_option_refusee_requete_simple(api):
    seen = api([(400, err("fallbacks: Extra inputs are not permitted")), (200, OK)])
    assert call().startswith("Quelle action")
    assert "fallbacks" in seen[0] and "fallbacks" not in seen[1]
    assert captions.last_error is None


def test_plus_de_credit(api):
    api([(400, err("Your credit balance is too low to access the Anthropic API."))])
    assert call() is None
    assert "Billing" in captions.last_error


def test_cle_refusee():
    assert "sk-ant-" in captions.explain_api_error(401, "invalid x-api-key")
