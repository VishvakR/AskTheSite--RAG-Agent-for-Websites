"""
Split inline ``<think>…</think>`` reasoning out of a token stream.

Local reasoning models (Qwen, DeepSeek-R1, …) often write their chain of
thought straight into the answer between think tags. Left alone, that text
lands in the chat bubble and gets cited, stored and exported as if it were the
answer. This parser routes it to a separate thinking channel instead.

It is a small state machine because tags routinely arrive split across chunks
(``"<thi"`` + ``"nk>"``): any suffix that could still become a tag is held back
until the next chunk decides it.
"""

from __future__ import annotations

from typing import List, Tuple

Segment = Tuple[str, str]  # ("text" | "thinking", content)

_PAIRS = {"<think>": "</think>", "<thinking>": "</thinking>"}


def _held_suffix(buf: str, tags) -> int:
    """Length of the longest suffix of *buf* that is a proper prefix of a tag."""
    best = 0
    for tag in tags:
        for n in range(min(len(tag) - 1, len(buf)), 0, -1):
            if buf.endswith(tag[:n]):
                best = max(best, n)
                break
    return best


class ThinkTagParser:
    def __init__(self) -> None:
        self._buf = ""
        self._close: str | None = None  # set while inside a think block
        self._strip_next = False

    @property
    def inside(self) -> bool:
        return self._close is not None

    def feed(self, chunk: str) -> List[Segment]:
        self._buf += chunk
        out: List[Segment] = []

        while self._buf:
            if self._close is None:
                hits = [(self._buf.find(t), t) for t in _PAIRS if t in self._buf]
                if hits:
                    idx, tag = min(hits)
                    self._emit(out, "text", self._buf[:idx])
                    self._buf = self._buf[idx + len(tag):]
                    self._close = _PAIRS[tag]
                    continue
                keep = _held_suffix(self._buf, _PAIRS)
            else:
                idx = self._buf.find(self._close)
                if idx >= 0:
                    self._emit(out, "thinking", self._buf[:idx])
                    self._buf = self._buf[idx + len(self._close):]
                    self._close = None
                    # Models put a blank line after </think>; don't start the
                    # answer with it.
                    self._strip_next = True
                    continue
                keep = _held_suffix(self._buf, [self._close])

            ready, self._buf = self._buf[: len(self._buf) - keep], self._buf[len(self._buf) - keep:]
            self._emit(out, "thinking" if self._close else "text", ready)
            break

        return out

    def flush(self) -> List[Segment]:
        out: List[Segment] = []
        self._emit(out, "thinking" if self._close else "text", self._buf)
        self._buf = ""
        return out

    def _emit(self, out: List[Segment], kind: str, text: str) -> None:
        if kind == "text" and self._strip_next:
            text = text.lstrip()
            if not text:
                return
            self._strip_next = False
        if not text:
            return
        if out and out[-1][0] == kind:
            out[-1] = (kind, out[-1][1] + text)
        else:
            out.append((kind, text))


def split_thinking(text: str) -> Tuple[str, str]:
    """Non-streaming helper: return ``(answer, thinking)`` for a whole string."""
    parser = ThinkTagParser()
    segments = parser.feed(text) + parser.flush()
    answer = "".join(s for k, s in segments if k == "text")
    thinking = "".join(s for k, s in segments if k == "thinking")
    return answer, thinking
