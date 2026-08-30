"""Full-duplex (phone-call) voice WebSocket for the interviewer agent.

Unlike the PTT endpoints (/api/voice/answer), this endpoint keeps ONE WebSocket
open for the whole call. The browser continuously uploads mic frames, the server
runs streaming STT (partials), detects turn end, calls the LLM for the next
interviewer line, and streams the TTS audio back in chunks — while the user can
still be heard (barge-in interrupts playback).

Protocol
--------
client -> server (JSON text, or raw binary for audio):
    {"type":"start"}                   begin a turn (STT accumulation)
    <binary frame>                     16k int16 mono PCM, 640-byte packets
    {"type":"audio","base64":"..."}    same audio, JSON fallback
    {"type":"stop"}                    finalize the current turn
    {"type":"interrupt"}               cut current AI playback immediately

server -> client (JSON text):
    {"type":"partial","text":"..."}    streaming STT partial
    {"type":"final","text":"..."}      turn-final transcript
    {"type":"spoken","text":"..."}     the full AI interviewer line
    {"type":"audio","base64":"..."}    one MP3 chunk (play immediately)
    {"type":"end_turn"}                this spoken turn finished (keep listening)
    {"type":"done"}                    the WHOLE interview is over (stop + report)
    {"type":"error","error":"..."}     non-fatal provider error

Flow: on `start` (or the first audio frame) begin STT accumulation; when STT
reports is_final or the client sends `stop`, run the LLM to produce the next
interviewer line, then stream TTS chunks as `audio` frames. If a mic frame
arrives while the AI line is playing, playback is cancelled and a NEW turn
starts (barge-in).

STT adapter: prefers `stt.stream_asr` (async generator yielding
(partial_text, is_final), being landed by the STT owner). If stt.py does not
expose `stream_asr` yet, degrades to one-shot `stt.transcribe_flash` so this
module is never broken by the exact stt API.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import logging
from typing import Any, AsyncIterator, Optional

from fastapi import WebSocket

from .llm import LLM
from .pipeline import ask_current
from .tts import synthesize_stream_async


def _flow_for(interview_id: str):
    """Live per-interview flow from main, if the interview has been started/prepared.

    Lazy import on purpose (main imports this module at startup). Degrades to None
    when the interview is unknown so the WS never hard-crashes on a missing id.
    """
    if not interview_id:
        return None
    try:
        from .main import _flow_for as _main_flow  # noqa: PLC0415

        return _main_flow(interview_id)
    except Exception:  # noqa: BLE001
        return None


def _can_start_now(interview_id: str) -> bool:
    """Whether the agent is allowed to answer (预约制: not before scheduled_at)."""
    if not interview_id:
        return True
    try:
        from .main import _can_start_now as _main_can_start  # noqa: PLC0415

        return _main_can_start(interview_id)
    except Exception:  # noqa: BLE001
        return True

logger = logging.getLogger("agent.voice_ws")

#: sentinel pushed onto the turn queue to signal "end of this turn's audio"
_END = object()

PCM_RATE = 16000
PCM_CHANNELS = 1
PCM_BITS = 16


# ---------------------------------------------------------------------------
# frame codecs (pure helpers — unit-testable offline)
# ---------------------------------------------------------------------------
def decode_client_frame(data: Any) -> tuple[str, Optional[bytes]]:
    """Classify one client frame -> (kind, payload_bytes).

    kind: "audio" (raw PCM or base64 JSON), "start" / "stop" / "interrupt"
    controls, or "unknown".
    """
    if isinstance(data, (bytes, bytearray, memoryview)):
        return "audio", bytes(data)
    if isinstance(data, str):
        try:
            obj = json.loads(data)
        except Exception:
            return "unknown", None
        t = obj.get("type")
        if t in ("start", "stop", "interrupt"):
            return t, None
        if t == "audio":
            b64 = obj.get("base64")
            if b64:
                try:
                    return "audio", base64.b64decode(b64)
                except Exception:
                    pass
    return "unknown", None


def build_server_frame(type_: str, **fields) -> str:
    """Encode a server -> client frame (unicode-safe JSON)."""
    return json.dumps({"type": type_, **fields}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# streaming STT adapter
# ---------------------------------------------------------------------------
def _load_stt_module():
    """Import agent.stt lazily so a freshly-deployed stt.py with stream_asr is
    picked up, and so importing this module never depends on stt internals."""
    import importlib

    return importlib.import_module(".stt", __package__)


def _first_param_name(fn) -> Optional[str]:
    try:
        sig = inspect.signature(fn)
        for p in sig.parameters.values():
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
                return p.name
            break
    except (TypeError, ValueError):
        pass
    return None


def _wants_queue(fn) -> bool:
    """Heuristic: does stream_asr take an asyncio.Queue instead of a frame iterator?"""
    name = (_first_param_name(fn) or "").lower()
    return "queue" in name or name in ("q", "in_q", "audio_q")


async def _frames_from_queue(queue: asyncio.Queue) -> AsyncIterator[bytes]:
    """Expose the turn queue as an async iterator of raw audio bytes
    (ends when the _END sentinel is pushed)."""
    while True:
        item = await queue.get()
        if item is _END:
            return
        yield item


async def stt_stream(
    frames: AsyncIterator[bytes],
    queue: asyncio.Queue,
    stt_module=None,
) -> AsyncIterator[tuple[str, bool]]:
    """Yield (text, is_final) from a stream of raw PCM frames.

    Preferred path: `stt.stream_asr(...)` (the streaming contract the STT owner
    is landing). Fallback: accumulate all frames and run one-shot
    `stt.transcribe_flash` when stream_asr is absent or unusable, so nothing
    here breaks before/after stt.py lands.
    """
    mod = stt_module if stt_module is not None else _load_stt_module()
    fn = getattr(mod, "stream_asr", None)
    if callable(fn):
        try:
            arg = queue if _wants_queue(fn) else frames
            res = fn(arg)
            if inspect.isawaitable(res):
                res = await res
            if hasattr(res, "__aiter__"):
                async for part, is_final in res:
                    yield part, is_final
                return
        except TypeError:
            logger.warning("stt.stream_asr signature mismatch; falling back to transcribe_flash", exc_info=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("stt.stream_asr failed mid-stream (%s); ending turn quietly", exc)
            yield "", True
            return
    # one-shot fallback: transcribe whatever frames were buffered
    buf = b""
    async for frame in frames:
        buf += frame
    if not buf:
        yield "", True
        return
    try:
        text = mod.transcribe_flash(base64.b64encode(buf).decode("ascii"), "wav")
        yield text or "", True
    except Exception as exc:  # noqa: BLE001
        logger.warning("stt.transcribe_flash fallback failed (%s)", exc)
        yield "", True


# ---------------------------------------------------------------------------
# interview context + LLM line
# ---------------------------------------------------------------------------
def _ctx_for(interview_id: str):
    """Live InterviewContext from main's registry, if the interview is prepared.

    Lazy import on purpose: main imports this module at startup, so importing
    main at module level here would be circular.
    """
    if not interview_id:
        return None
    try:
        from .main import _CONTEXTS  # noqa: PLC0415

        return _CONTEXTS.get(interview_id)
    except Exception:  # noqa: BLE001
        return None


def _persona_prompt(persona: str) -> str:
    return {
        "peer": "你是一位平级同事面试官，语气随和，但会深入考察技术细节。",
        "high-peer": "你是一位资深同侪面试官，专业、直接，追问犀利，注重考察真本事。",
        "manager": "你是一位高级经理面试官，注重候选人的整体素质、表达和潜力。",
    }.get(persona, "你是一位资深技术面试官。")


# ---------------------------------------------------------------------------
# per-connection full-duplex session
# ---------------------------------------------------------------------------
class VoiceSession:
    """One full-duplex voice session per WebSocket connection."""

    def __init__(self, ws: WebSocket, interview_id: str = ""):
        self.ws = ws
        self.interview_id = interview_id
        self.queue: Optional[asyncio.Queue] = None  # audio frames of current turn
        self.turn_task: Optional[asyncio.Task] = None
        self.playback_active = False
        self._announced = False  # the opening question is spoken at most once
        self._processing = False  # a turn is past STT and running the LLM/response
        self._pending_frames: list[bytes] = []  # mic frames arriving mid-LLM (barge-in)
        self._barging = False  # switched to a candidate turn while playing

    # ---- receive side ----------------------------------------------------
    async def run(self) -> None:
        """Main receive loop; returns on client disconnect."""
        await self.ws.accept()
        try:
            while True:
                try:
                    msg = await self.ws.receive()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - disconnect/channel-cancel races
                    logger.debug("voice ws receive dropped: %s", exc)
                    break
                if msg is None:
                    break
                if msg.get("type") == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    self._on_audio(bytes(msg["bytes"]))
                    continue
                text = msg.get("text")
                if not text:
                    continue
                kind, payload = decode_client_frame(text)
                if kind == "audio" and payload:
                    self._on_audio(payload)
                elif kind == "start":
                    # The candidate is ready: open the call by speaking the opening.
                    asyncio.create_task(self._maybe_announce_question())
                elif kind == "stop":
                    self._end_turn()
                elif kind == "interrupt":
                    self._interrupt()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("voice ws receive error: %s", exc)
        finally:
            self._interrupt()

    def _begin_turn(self) -> None:
        """Start STT accumulation for a new turn (cancels any active playback)."""
        self._interrupt()
        q: asyncio.Queue = asyncio.Queue()
        self.queue = q
        self._processing = False
        self._barging = False
        self.turn_task = asyncio.create_task(self._turn_worker(q))

    async def _maybe_announce_question(self) -> None:
        """If the interview has no answers yet, speak the opening question.

        Guarded by ``_announced`` (and the flow's own idempotent opening_line) so the
        opening is spoken exactly once, even if the candidate's first mic frames
        trigger a barge-in mid-announce.
        """
        if self._announced:
            return
        # 预约制：时间未到，不开口、不推进。
        if not _can_start_now(self.interview_id):
            return
        try:
            flow = _flow_for(self.interview_id)
        except Exception:  # noqa: BLE001
            flow = None
        if flow is None:
            return
        if flow.done:
            return
        q = flow.opening_line()  # idempotent; returns the self-intro request
        if not q or flow.done:
            return
        self._announced = True
        section, phase = self._current_section_phase()
        await self._send({"type": "spoken", "text": q, "section": section, "phase": phase})
        self.playback_active = True
        try:
            async for chunk in synthesize_stream_async(q):
                await self._send({"type": "audio", "base64": base64.b64encode(chunk).decode("ascii")})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("tts announce failed: %s", exc)
        finally:
            self.playback_active = False

    def _end_turn(self) -> None:
        """Finalize the current turn: flush STT, then AI line + TTS."""
        if self.queue is not None and self.turn_task is not None and not self.turn_task.done():
            self.queue.put_nowait(_END)

    def _interrupt(self) -> None:
        """Cut current AI playback and discard the in-flight turn's audio."""
        if self.turn_task is not None and not self.turn_task.done():
            self.turn_task.cancel()
        self.turn_task = None
        self.queue = None
        self.playback_active = False
        self._processing = False

    def _on_audio(self, frame: bytes) -> None:
        """Barge-in aware audio ingest.

        - While the AI is PLAYING (no LLM in flight): any audio is a barge-in —
          cancel playback and start a fresh candidate turn.
        - While a turn is PROCESSING (LLM/response in flight): buffer the mic frames
          so we don't start a second turn (which would double-advance the flow);
          drain them when the current turn completes.
        - Otherwise: feed frames into the active turn's STT queue.
        """
        if not frame:
            return
        if self._processing:
            self._pending_frames.append(frame)
            return
        if self.playback_active:
            self._barging = True
            self._begin_turn()  # cancels playback, opens a fresh candidate turn
        if self.queue is None:
            self._begin_turn()
            # The candidate started talking before we announced (or without `start`):
            # make sure the opening is spoken at most once, in parallel.
            asyncio.create_task(self._maybe_announce_question())
        if self.queue is not None and self.turn_task is not None and not self.turn_task.done():
            self.queue.put_nowait(frame)

    # ---- send side -------------------------------------------------------
    async def _send(self, obj: dict) -> None:
        try:
            await self.ws.send_text(json.dumps(obj, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            pass  # socket closed / cancelled mid-send: drop the frame

    # ---- turn worker -----------------------------------------------------
    async def _turn_worker(self, queue: asyncio.Queue) -> None:
        try:
            await self._run_turn(queue)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("voice turn failed")
            await self._send({"type": "error", "error": f"turn: {exc}"})
        finally:
            if self.turn_task is asyncio.current_task():
                self.turn_task = None
                self.queue = None
                self._processing = False
                self._drain_pending()

    def _drain_pending(self) -> None:
        """If the candidate spoke while the AI was processing, start their turn now."""
        if self._pending_frames:
            frames = self._pending_frames
            self._pending_frames = []
            self._begin_turn()
            if self.queue is not None and self.turn_task is not None:
                for f in frames:
                    self.queue.put_nowait(f)

    async def _run_turn(self, queue: asyncio.Queue) -> None:
        final_text = ""
        try:
            async for text, is_final in stt_stream(_frames_from_queue(queue), queue):
                if text:
                    final_text = text
                if is_final:
                    break
                await self._send({"type": "partial", "text": text})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("stt loop failed: %s", exc)
            await self._send({"type": "error", "error": f"stt: {exc}"})
            await self._end_or_continue()
            return
        await self._send({"type": "final", "text": final_text})
        if not final_text.strip():
            # Nothing recognized: don't advance, just let the caller keep listening.
            await self._end_or_continue()
            return
        # LLM + response phase — buffer any concurrent mic frames for the next turn.
        self._processing = True
        line = await self._next_interviewer_line(final_text)
        self._processing = False
        if not line:
            await self._end_or_continue()
            return
        section, phase = self._current_section_phase()
        await self._send({"type": "spoken", "text": line, "section": section, "phase": phase})
        self.playback_active = True
        try:
            async for chunk in synthesize_stream_async(line):
                await self._send({"type": "audio", "base64": base64.b64encode(chunk).decode("ascii")})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("tts stream failed: %s", exc)
            await self._send({"type": "error", "error": f"tts: {exc}"})
        finally:
            self.playback_active = False
        await self._end_or_continue()

    async def _end_or_continue(self) -> None:
        """Send the correct end-of-turn signal.

        `done` means the WHOLE interview is over (client stops + shows report); a
        normal turn end is `end_turn` (client keeps listening for the next result).
        """
        if self._is_over():
            await self._send({"type": "done"})
        else:
            await self._send({"type": "end_turn"})

    def _is_over(self) -> bool:
        try:
            flow = _flow_for(self.interview_id)
        except Exception:  # noqa: BLE001
            flow = None
        return bool(flow and flow.done)

    def _current_section_phase(self) -> tuple[str, str]:
        """(section, phase) of the live flow, for the UI to reveal the coding round."""
        try:
            flow = _flow_for(self.interview_id)
        except Exception:  # noqa: BLE001
            flow = None
        if flow is None:
            return "technical", ""
        return flow.section_for_ui(), flow.phase

    async def _next_interviewer_line(self, user_text: str) -> str:
        """Per-round interviewer line from the LiveFlow agent: persona + resume +
        this interview's requirements + FULL chat history. Advances the interview
        (self-intro -> project -> probe -> coding -> wrap) with time awareness."""
        # 预约制：时间未到，agent 不回复。
        if not _can_start_now(self.interview_id):
            return "未到预约时间，暂不能答题。请到预约时间后再开始。"
        try:
            flow = _flow_for(self.interview_id)
        except Exception:  # noqa: BLE001
            flow = None
        if flow is None:
            # Fallback (interview not prepared/known): keep the old conversational line.
            return await self._legacy_next_line(user_text)
        if flow.done:
            return "面试已结束，感谢你的回答，可以查看你的报告了。"
        # flow.next_line records the answer + a PlannedQuestion for scoring internally.
        # It is a BLOCKING LLM call — run it off the event loop.
        line = await asyncio.to_thread(flow.next_line, user_text)
        return line or "请继续，说说你的想法。"

    async def _legacy_next_line(self, user_text: str) -> str:
        """Backup conversational line when no LiveFlow exists (legacy path)."""
        ctx = _ctx_for(self.interview_id)
        q = ask_current(ctx) if ctx is not None else None
        if ctx is not None and q is None:
            return "面试已结束，感谢你的回答，可以查看你的报告了。"
        persona = _persona_prompt(getattr(ctx, "persona", "high-peer") if ctx is not None else "high-peer")
        system = (
            persona
            + "请用中文口语化地说一句话（通常不超过60字），像真实的电话面试。"
            + "根据候选人刚才的回答自然地继续引导、追问或衔接下一个话题，不要复述题目，不要提评分。"
        )
        user = f"当前问题：{q}\n候选人回答：{user_text}\n请说出你接下来的话。"
        try:
            llm = LLM()
            line = await asyncio.to_thread(
                llm.chat,
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=256,
                temperature=0.7,
                timeout=45.0,
            )
            return (line or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("llm next-line failed: %s", exc)
            await self._send({"type": "error", "error": f"llm: {exc}"})
            return ""


async def voice_ws_handler(websocket: WebSocket, interview_id: str = "") -> None:
    """Route entry point: run a full-duplex voice session on `websocket`."""
    session = VoiceSession(websocket, interview_id)
    await session.run()
