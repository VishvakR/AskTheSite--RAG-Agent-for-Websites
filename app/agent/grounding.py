"""
The grounding meter: how much of an answer is actually backed by a source.

Citations are only useful if they're there. After every answer this checks
each substantive sentence for a valid ``[n]`` marker and reports:

* ``score`` -- share of sentences that are supported,
* ``uncited`` -- the claims with nothing behind them (worth a second look),
* ``invalid_markers`` -- numbers that point at no retrieved source,
* ``unused_sources`` -- retrieved chunks the answer never relied on.

A sentence also counts as supported when the *next* sentence in the same
paragraph carries the citation, since people (and models) often cite once at
the end of a two-sentence point. Headings, code, very short fragments and
"the sources don't say" disclaimers are not claims and are skipped.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

_MARKER = re.compile(r"\[(\d+)\]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[*_`])")
_FENCE = re.compile(r"```.*?```", re.S)
_LIST_ITEM = re.compile(r"^([-*+]|\d+[.)])\s+")
_DISCLAIMER = re.compile(
    r"\b(do(es)? not (mention|say|cover|contain)|don't (mention|say|cover)|"
    r"no (information|mention)|couldn't find|could not find|not (covered|mentioned) in)\b",
    re.I,
)
MIN_WORDS = 5


def _paragraphs(text: str) -> Iterable[List[str]]:
    text = _FENCE.sub("", text)
    for block in re.split(r"\n\s*\n", text):
        prose: List[str] = []
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "|", ">")):
                continue
            item = _LIST_ITEM.match(line)
            if item:
                # Each list item is its own claim.
                yield _split(line[item.end():])
            else:
                prose.append(line)
        if prose:
            yield _split(" ".join(prose))


def _split(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE.split(text) if s.strip()]


def assess(answer: str, citations: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    known = {int(c["marker"]) for c in citations if "marker" in c}
    total = supported = 0
    uncited: List[str] = []
    used: set[int] = set()
    invalid: set[int] = set()

    for sentences in _paragraphs(answer):
        marks = [{int(m) for m in _MARKER.findall(s)} for s in sentences]
        for i, sentence in enumerate(sentences):
            for m in marks[i]:
                (used if m in known else invalid).add(m)
            plain = _MARKER.sub("", sentence)
            if len(plain.split()) < MIN_WORDS or _DISCLAIMER.search(plain):
                continue
            total += 1
            here = marks[i] & known
            nxt = marks[i + 1] & known if i + 1 < len(sentences) else set()
            if here or nxt:
                supported += 1
            else:
                uncited.append(plain.strip()[:200])

    score = round(supported / total, 3) if total else None
    if score is None:
        label = "n/a"
    elif score >= 0.8:
        label = "grounded"
    elif score >= 0.4:
        label = "partly grounded"
    else:
        label = "ungrounded"

    return {
        "score": score,
        "label": label,
        "sentences": total,
        "supported": supported,
        "uncited": uncited[:5],
        "invalid_markers": sorted(invalid),
        "unused_sources": sorted(known - used),
    }
