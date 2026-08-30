"""Offline tests for the full-duplex voice WebSocket: pure helpers, the
streaming-STT adapter (with/without stt.stream_asr), and a fully-mocked
end-to-end WebSocket flow. No network involved.

Run: cd apps/agent && .venv/bin/python -m pytest tests/test_voice_ws.py -q
"""

import asyncio
import base64
import json

from fastapi.testclient import TestClient

from agent.main import app
import agent.voice_ws as vws


# ---------------------------------------------------------------------------
# pure frame codecs
# ---------------------------------------------------------------------------
def test_decode_binary_frame_is_audio():
    kind, payload = vws.decode_client_frame(b"\x00" * 640)
    assert kind == "audio"
    assert payload == b"\x00" * 640


def test_decode_json_control_frames():
    assert vws.decode_client_frame('{"type":"start"}') == ("start", None)
    assert vws.decode_client_frame('{"type":"stop"}') == ("stop", None)
    assert vws.decode_client_frame('{"type":"interrupt"}') == ("interrupt", None)


def test_decode_json_audio_base64():
    raw = b"\x01\x02" * 100
    kind, payload = vws.decode_client_frame(
        json.dumps({"type": "audio", "base64": base64.b64encode(raw).decode()})
    )
    assert kind == "audio"
    assert payload == raw


def test_decode_garbage_is_unknown():
    assert vws.decode_client_frame("not json")[0] == "unknown"
    assert vws.decode_client_frame('{"type":"nope"}')[0] == "unknown"
    assert vws.decode_client_frame(b"")[0] == "audio"  # empty binary is still audio-ish


def test_build_server_frame_keeps_unicode():
    frame = json.loads(vws.build_server_frame("partial", text="你好"))
    assert frame["type"] == "partial"
    assert frame["text"] == "你好"


# ---------------------------------------------------------------------------
# streaming STT adapter
# ---------------------------------------------------------------------------
class _FakeStreamSTT:
    """Mimics the colleague's stream_asr contract: (partial_text, is_final)."""

    async def stream_asr(self, frames):
        got = b""
        async for f in frames:
            got += f
        if got:
            yield "你", False
            yield "你好，请介绍下你自己", True
        else:
            yield "", True

    def transcribe_flash(self, audio_b64, fmt="wav"):
        raise AssertionError("stream path must be used, not flash")


def test_stt_adapter_uses_stream_asr_when_present():
    async def run():
        q = asyncio.Queue()
        q.put_nowait(b"\x00" * 640)
        q.put_nowait(vws._END)
        return [pair async for pair in vws.stt_stream(vws._frames_from_queue(q), q, stt_module=_FakeStreamSTT())]

    out = asyncio.run(run())
    assert out == [("你", False), ("你好，请介绍下你自己", True)]


class _ColleagueStreamSTT:
    """Mirrors the exact signature that landed in stt.py:
    stream_asr(bytes_iter, fmt="pcm", chunk_size=None, timeout=20.0)."""

    async def stream_asr(self, bytes_iter, fmt="pcm", chunk_size=None, timeout=20.0):
        got = b""
        async for f in bytes_iter:
            got += f
        if got:
            yield "你好，请介绍下你自己", True
        else:
            yield "", True

    def transcribe_flash(self, audio_b64, fmt="wav"):
        raise AssertionError("stream path must be used, not flash")


def test_wants_queue_false_for_landed_signature():
    """bytes_iter first param => adapter passes the frame iterator, not a queue."""
    assert vws._wants_queue(_ColleagueStreamSTT.stream_asr) is False


def test_stt_adapter_wires_to_landed_signature():
    async def run():
        q = asyncio.Queue()
        q.put_nowait(b"\x00" * 640)
        q.put_nowait(vws._END)
        return [pair async for pair in vws.stt_stream(vws._frames_from_queue(q), q, stt_module=_ColleagueStreamSTT())]

    out = asyncio.run(run())
    assert out == [("你好，请介绍下你自己", True)]


class _NoStreamSTT:
    """stt.py WITHOUT stream_asr yet (the current pre-colleague state)."""

    calls = []

    def transcribe_flash(self, audio_b64, fmt="wav"):
        _NoStreamSTT.calls.append((audio_b64, fmt))
        return "回退识别结果"


def test_stt_adapter_falls_back_to_flash_without_stream_asr():
    async def run():
        q = asyncio.Queue()
        q.put_nowait(b"\x00" * 640)
        q.put_nowait(vws._END)
        return [pair async for pair in vws.stt_stream(vws._frames_from_queue(q), q, stt_module=_NoStreamSTT())]

    _NoStreamSTT.calls = []
    out = asyncio.run(run())
    assert out == [("回退识别结果", True)]
    assert len(_NoStreamSTT.calls) == 1
    assert _NoStreamSTT.calls[0][1] == "wav"  # flash fallback formats PCM as wav


def test_stt_adapter_empty_audio_ends_turn():
    async def run():
        q = asyncio.Queue()
        q.put_nowait(vws._END)
        return [pair async for pair in vws.stt_stream(vws._frames_from_queue(q), q, stt_module=_NoStreamSTT())]

    out = asyncio.run(run())
    assert out == [("", True)]  # silence -> empty final, no flash call


# ---------------------------------------------------------------------------
# session state machine: barge-in / interrupt (pure, no WS, no network)
# ---------------------------------------------------------------------------
class _FakeWS:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def receive(self):
        return {"type": "websocket.disconnect"}

    async def send_text(self, s):
        self.sent.append(s)


def _new_session(monkeypatch):
    """VoiceSession with stt adapter pointed at the fake streaming module."""
    monkeypatch.setattr(vws, "_load_stt_module", lambda: _FakeStreamSTT())
    return vws.VoiceSession(_FakeWS(), "x")


def test_first_audio_implicitly_starts_turn(monkeypatch):
    async def scenario():
        s = _new_session(monkeypatch)
        assert s.queue is None and s.turn_task is None
        s._on_audio(b"\x00" * 640)
        task = s.turn_task
        frame = s.queue.get_nowait()
        task.cancel()  # clean up the worker task
        try:
            await task
        except asyncio.CancelledError:
            pass
        return frame

    assert asyncio.run(scenario()) == b"\x00" * 640


def test_barge_in_replaces_turn_and_feeds_frame(monkeypatch):
    async def scenario():
        s = _new_session(monkeypatch)
        s._begin_turn()
        old_task = s.turn_task
        s.playback_active = True  # AI line is playing
        s._on_audio(b"\x11" * 640)  # user starts talking over it
        new_task = s.turn_task
        frame = s.queue.get_nowait()
        old_task.cancel()
        new_task.cancel()
        for t in (old_task, new_task):
            try:
                await t
            except asyncio.CancelledError:
                pass
        return new_task is not old_task, not s.playback_active, frame

    replaced, playback_off, frame = asyncio.run(scenario())
    assert replaced  # a fresh turn was opened
    assert playback_off  # playback was cut
    assert frame == b"\x11" * 640  # the barge-in frame went to the new turn


def test_interrupt_cancels_and_clears(monkeypatch):
    async def scenario():
        s = _new_session(monkeypatch)
        s._begin_turn()
        s.playback_active = True
        task = s.turn_task
        s._interrupt()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return s.queue, s.turn_task, s.playback_active

    q, t, p = asyncio.run(scenario())
    assert q is None and t is None and p is False


# ---------------------------------------------------------------------------
# end-to-end WebSocket flow, everything mocked (no network)
# ---------------------------------------------------------------------------
class _FakeLLM:
    def __init__(self, *a, **k):
        pass

    def chat(self, messages, **kwargs):
        assert any("候选人回答" in str(m.get("content", "")) for m in messages)
        return "好的，那你具体是怎么解决这个问题的？"


async def _fake_tts(text):
    yield b"ID3fake"
    yield b"\x00" * 1024


def test_full_duplex_ws_flow(monkeypatch):
    monkeypatch.setattr(vws, "_load_stt_module", lambda: _FakeStreamSTT())
    monkeypatch.setattr(vws, "LLM", _FakeLLM)
    monkeypatch.setattr(vws, "synthesize_stream_async", _fake_tts)

    frames = []
    client = TestClient(app)
    with client.websocket_connect("/ws/voice?interview_id=does-not-exist") as ws:
        ws.send_text('{"type":"start"}')
        ws.send_bytes(b"\x00" * 640)
        ws.send_text('{"type":"stop"}')
        # partial, final, spoken, audio, audio, done
        for _ in range(6):
            frames.append(ws.receive_json())
        ws.close()

    types = [f["type"] for f in frames]
    assert types[0] == "partial" and frames[0]["text"] == "你"
    assert types[1] == "final" and frames[1]["text"] == "你好，请介绍下你自己"
    assert types[2] == "spoken" and "解决" in frames[2]["text"]
    assert types[3] == "audio" and types[4] == "audio"
    assert base64.b64decode(frames[3]["base64"]) == b"ID3fake"
    # No prepared LiveFlow -> the interview is not over -> normal end is `end_turn`,
    # NOT `done` (which would incorrectly end the whole interview after one exchange).
    assert types[5] == "end_turn"
