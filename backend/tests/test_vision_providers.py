import base64
import json
import os
import subprocess
from types import SimpleNamespace

from app.providers.claude_agent import ClaudeAgentProvider
from app.providers.claude_api import ClaudeApiProvider


def _fake_run(captured):
    def run(cmd, **kw):
        captured["cmd"], captured["kw"] = cmd, kw
        captured["copy_existed"] = os.path.exists(os.path.join(kw["cwd"], "page.jpg")) if kw.get("cwd") else None
        return SimpleNamespace(
            stdout=json.dumps({"result": "READ OK", "subtype": "success"}).encode(), stderr=b""
        )

    return run


def test_cli_vision_enables_only_the_read_tool_on_a_private_copy(monkeypatch, tmp_path):
    img = tmp_path / "secret-page.jpg"
    img.write_bytes(b"jpeg")
    captured = {}
    monkeypatch.setattr(subprocess, "run", _fake_run(captured))

    out = ClaudeAgentProvider().vision("Transcribe.", str(img), system="SYSTEM")
    assert out == "READ OK"

    cmd = captured["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "Read"
    assert cmd[cmd.index("--allowedTools") + 1] == "Read"
    assert captured["copy_existed"] is True                       # the copy was there during the call
    assert os.path.dirname(str(img)) != captured["kw"]["cwd"]     # runs in a temp dir, not next to the photo
    prompt = captured["kw"]["input"].decode()
    assert "./page.jpg" in prompt and "Transcribe." in prompt and "secret-page" not in prompt
    assert not os.path.exists(captured["kw"]["cwd"])              # temp copy is removed afterwards


def test_cli_text_calls_keep_every_tool_disabled(monkeypatch):
    captured = {}
    monkeypatch.setattr(subprocess, "run", _fake_run(captured))
    ClaudeAgentProvider().chat("salom")
    cmd = captured["cmd"]
    assert cmd[cmd.index("--tools") + 1] == "" and "--allowedTools" not in cmd


def test_api_vision_sends_a_base64_image_block(tmp_path):
    img = tmp_path / "p.png"
    img.write_bytes(b"\x89PNGdata")
    seen = {}

    class Messages:
        def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="  JSON  ")])

    provider = ClaudeApiProvider.__new__(ClaudeApiProvider)
    provider._client, provider._model = SimpleNamespace(messages=Messages()), "m"
    assert provider.vision("Read it", str(img), system="SYS") == "JSON"

    block, text = seen["messages"][0]["content"]
    assert block["type"] == "image" and block["source"]["media_type"] == "image/png"
    assert base64.b64decode(block["source"]["data"]) == b"\x89PNGdata"
    assert text == {"type": "text", "text": "Read it"} and seen["system"] == "SYS"
