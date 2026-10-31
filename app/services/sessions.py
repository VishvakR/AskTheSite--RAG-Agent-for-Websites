"""
Chat sessions: persistence, history replay, and the shapes the UIs read.

A session is an ordered list of :class:`MessageRecord` rows. Everything the
model saw is stored -- including an agent's intermediate tool calls and their
results -- so replaying history is exact. The UIs don't want that raw list,
though; :func:`turns` folds it into one entry per question.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional

from app.catalog import (
    MessageRecord,
    Session,
    SessionMode,
    get_catalog,
    new_id,
)
from app.llm import ChatMessage, LLMManager, ToolCall

logger = logging.getLogger(__name__)

TITLE_MAX = 60
# Share of the context window history may use before older turns are folded
# into a summary; the rest is left for sources, tools and the answer.
HISTORY_BUDGET = 0.7


class SessionNotFound(Exception):
    pass


def require(session_id: str) -> Session:
    session = get_catalog().get_session(session_id)
    if session is None:
        raise SessionNotFound(f"No session with id {session_id!r}")
    return session


# ── CRUD ──────────────────────────────────────────────────────────────────


def _validate(
    mode: Optional[str] = None,
    workspace_ids: Optional[List[str]] = None,
    provider: Optional[str] = None,
) -> None:
    if mode is not None and mode not in SessionMode.ALL:
        raise ValueError(f"Unknown mode {mode!r}; expected one of {sorted(SessionMode.ALL)}")
    if provider is not None:
        LLMManager.provider_class(provider)  # raises ValueError if unknown
    for ws_id in workspace_ids or []:
        if get_catalog().get_workspace(ws_id) is None:
            raise ValueError(f"No workspace with id {ws_id!r}")


def create_session(
    workspace_ids: Optional[List[str]] = None,
    title: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    mode: str = SessionMode.RAG,
    engine: str = "auto",
    top_k: int = 5,
    thinking: Optional[Dict[str, Any]] = None,
    system_prompt: Optional[str] = None,
) -> Session:
    workspace_ids = list(dict.fromkeys(workspace_ids or []))
    _validate(mode, workspace_ids, provider)
    if provider is None:
        provider, default_model = LLMManager.default_selection()
        model = model or default_model
    session = Session(
        id=new_id(),
        title=title or "New chat",
        workspace_ids=workspace_ids,
        provider=provider,
        model=model,
        mode=mode,
        engine=engine,
        top_k=top_k,
        thinking=thinking,
        system_prompt=system_prompt,
    )
    return get_catalog().create_session(session)


def list_sessions(workspace_id: Optional[str] = None, limit: int = 100) -> List[Session]:
    return get_catalog().list_sessions(workspace_id, limit)


def update_session(session_id: str, **fields: Any) -> Session:
    require(session_id)
    _validate(fields.get("mode"), fields.get("workspace_ids"), fields.get("provider"))
    if "workspace_ids" in fields:
        fields["workspace_ids"] = list(dict.fromkeys(fields["workspace_ids"]))
    return get_catalog().update_session(session_id, **fields)


def delete_session(session_id: str) -> bool:
    return get_catalog().delete_session(session_id)


def search(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    return get_catalog().search_messages(query, limit)


def title_from(prompt: str) -> str:
    """A readable title from the first question -- no model call needed."""
    line = " ".join(prompt.split())
    if len(line) <= TITLE_MAX:
        return line or "New chat"
    cut = line[:TITLE_MAX].rsplit(" ", 1)[0]
    return f"{cut}…"


# ── message conversion ───────────────────────────────────────────────────


#: ``raw_provider`` marking a user message whose ``raw`` holds the full
#: prompt the model saw (sources + question) while ``content`` keeps just the
#: question for display. Replay sends ``raw`` so history is exact.
AUGMENTED = "augmented"

#: ``name`` on a user message the harness injected (e.g. the step-limit
#: notice). Replayed to the model, never shown as the user's question.
HARNESS_NOTE = "harness"


def to_chat(record: MessageRecord) -> ChatMessage:
    if record.role == "user" and record.raw_provider == AUGMENTED and record.raw:
        return ChatMessage.user(str(record.raw))
    return ChatMessage(
        role=record.role,  # type: ignore[arg-type]
        content=record.content or "",
        thinking=record.thinking or "",
        tool_calls=[ToolCall.from_dict(c) for c in record.tool_calls or []],
        tool_call_id=record.tool_call_id,
        name=record.name,
        is_error=record.is_error,
        raw=record.raw,
        raw_provider=record.raw_provider,
    )


def append(
    session_id: str, turn_id: str, message: ChatMessage, **extra: Any
) -> MessageRecord:
    """Persist one :class:`ChatMessage`, plus any per-message metadata."""
    record = MessageRecord(
        id=new_id(),
        session_id=session_id,
        turn_id=turn_id,
        seq=0,
        role=message.role,
        content=message.content,
        thinking=message.thinking or None,
        tool_calls=[c.to_dict() for c in message.tool_calls] or None,
        tool_call_id=message.tool_call_id,
        name=message.name,
        is_error=message.is_error,
        raw=message.raw,
        raw_provider=message.raw_provider,
        **extra,
    )
    get_catalog().add_message(record)
    get_catalog().touch_session(session_id)
    return record


# ── history ──────────────────────────────────────────────────────────────


def estimate_tokens(messages: Iterable[ChatMessage]) -> int:
    """Rough count (≈4 chars/token) -- good enough to budget a context window."""
    chars = 0
    for m in messages:
        chars += len(m.content) + len(m.thinking)
        for c in m.tool_calls:
            chars += len(c.name) + len(json.dumps(c.arguments))
    return chars // 4


def history(session: Session) -> List[ChatMessage]:
    """
    Messages to replay before the next question: the rolling summary (if
    older turns were folded into one) followed by every message after it.
    """
    records = get_catalog().list_messages(session.id, after_seq=session.summary_upto)
    out: List[ChatMessage] = []
    if session.summary:
        out.append(
            ChatMessage.system(f"Summary of the earlier conversation:\n{session.summary}")
        )
    out.extend(to_chat(r) for r in records)
    return out


def needs_compaction(session: Session, context_window: int) -> bool:
    # Anthropic models have a 1M window and bind their thinking blocks to an
    # unedited history, so rewriting it into a summary would cost more than
    # it saves. Everything else is compacted once history gets heavy.
    if session.provider == "anthropic":
        return False
    return estimate_tokens(history(session)) > HISTORY_BUDGET * context_window


def compact(session: Session, llm: Any, keep_turns: int = 2) -> Optional[Session]:
    """
    Fold every turn except the last *keep_turns* into the session summary.

    Returns the updated session, or ``None`` when there is nothing old enough
    to fold.
    """
    from app.llm import chat
    from app.llm.types import TextDelta

    records = get_catalog().list_messages(session.id, after_seq=session.summary_upto)
    turn_order = list(dict.fromkeys(r.turn_id for r in records))
    if len(turn_order) <= keep_turns:
        return None
    folded = set(turn_order[:-keep_turns])
    old = [r for r in records if r.turn_id in folded]

    transcript = "\n\n".join(
        f"{r.role.upper()}: {r.content}" for r in old if r.role in ("user", "assistant") and r.content
    )
    prompt = [
        ChatMessage.system(
            "Summarise this conversation so it can replace the original in a "
            "model's context. Keep facts, names, URLs, decisions and open "
            "questions. Drop pleasantries. Plain prose, under 250 words."
        ),
        ChatMessage.user(
            (f"Existing summary:\n{session.summary}\n\n" if session.summary else "")
            + f"New turns:\n{transcript}"
        ),
    ]
    summary = "".join(e.text for e in chat(llm, prompt) if isinstance(e, TextDelta)).strip()
    if not summary:
        return None
    return get_catalog().update_session(
        session.id, summary=summary, summary_upto=max(r.seq for r in old)
    )


# ── views ────────────────────────────────────────────────────────────────


def turns(session_id: str) -> List[Dict[str, Any]]:
    """
    Fold a session's messages into one entry per question:
    ``{turn_id, user, steps, answer}``. ``steps`` pairs each tool call with its
    result; ``answer`` is the final assistant message with its citations,
    grounding, follow-ups and usage, and the reasoning from every step.
    """
    out: List[Dict[str, Any]] = []
    by_turn: Dict[str, Dict[str, Any]] = {}
    results: Dict[str, MessageRecord] = {}

    records = get_catalog().list_messages(session_id)
    for r in records:
        if r.role == "tool" and r.tool_call_id:
            results[r.tool_call_id] = r

    for r in records:
        turn = by_turn.get(r.turn_id)
        if turn is None:
            turn = {"turn_id": r.turn_id, "user": None, "steps": [], "answer": None, "_thinking": []}
            by_turn[r.turn_id] = turn
            out.append(turn)

        if r.role == "user":
            if r.name != HARNESS_NOTE and turn["user"] is None:
                turn["user"] = {"id": r.id, "content": r.content, "created_at": r.created_at}
        elif r.role == "assistant":
            if r.thinking:
                turn["_thinking"].append(r.thinking)
            for call in r.tool_calls or []:
                result = results.get(call["id"])
                turn["steps"].append({
                    "id": call["id"],
                    "name": call["name"],
                    "arguments": call.get("arguments") or {},
                    "result": result.content if result else None,
                    "is_error": bool(result and result.is_error),
                    "elapsed_ms": result.elapsed_ms if result else None,
                })
            if not r.tool_calls:
                turn["answer"] = r.to_dict()

    for turn in out:
        thinking = turn.pop("_thinking")
        if turn["answer"] is not None:
            turn["answer"]["thinking"] = "\n\n".join(thinking) or None
    return out


def detail(session_id: str) -> Dict[str, Any]:
    session = require(session_id)
    return {"session": session.to_dict(), "turns": turns(session_id)}


# ── edit, regenerate, fork ───────────────────────────────────────────────


def truncate_at_turn(session_id: str, turn_id: str) -> str:
    """
    Remove *turn_id* and everything after it; return that turn's question so
    the caller can re-ask it (regenerate) or ask an edited version.

    Only ever cuts a suffix, so the remaining history is byte-for-byte the
    prefix the model already saw.
    """
    records = get_catalog().list_messages(session_id)
    first = next((r for r in records if r.turn_id == turn_id), None)
    if first is None:
        raise ValueError(f"No turn {turn_id!r} in session {session_id!r}")
    question = next(
        (
            r.content
            for r in records
            if r.turn_id == turn_id and r.role == "user" and r.name != HARNESS_NOTE
        ),
        "",
    )
    get_catalog().delete_messages_from(session_id, first.seq)
    session = require(session_id)
    if session.summary_upto >= first.seq:
        get_catalog().update_session(session_id, summary=None, summary_upto=0)
    return question


def fork(session_id: str, upto_turn_id: Optional[str] = None) -> Session:
    """Copy a session -- optionally only up to and including one turn."""
    source = require(session_id)
    copy = create_session(
        workspace_ids=source.workspace_ids,
        title=f"{source.title} (fork)",
        provider=source.provider,
        model=source.model,
        mode=source.mode,
        engine=source.engine,
        top_k=source.top_k,
        thinking=source.thinking,
        system_prompt=source.system_prompt,
    )
    catalog = get_catalog()
    records = catalog.list_messages(session_id)
    if upto_turn_id:
        last = max((r.seq for r in records if r.turn_id == upto_turn_id), default=None)
        if last is None:
            raise ValueError(f"No turn {upto_turn_id!r} in session {session_id!r}")
        records = [r for r in records if r.seq <= last]
    for r in records:
        r.id = new_id()
        r.session_id = copy.id
        catalog.add_message(r)
    if source.summary and records and source.summary_upto <= records[-1].seq:
        catalog.update_session(copy.id, summary=source.summary, summary_upto=source.summary_upto)
    return catalog.get_session(copy.id)


def set_feedback(message_id: str, value: int) -> MessageRecord:
    if value not in (-1, 0, 1):
        raise ValueError("feedback must be -1, 0 or 1")
    record = get_catalog().update_message(message_id, feedback=value)
    if record is None:
        raise ValueError(f"No message with id {message_id!r}")
    return record


# ── export ───────────────────────────────────────────────────────────────


def export(session_id: str, fmt: str = "markdown") -> str:
    session = require(session_id)
    data = turns(session_id)
    if fmt == "json":
        return json.dumps({"session": session.to_dict(), "turns": data}, indent=2)
    if fmt != "markdown":
        raise ValueError("format must be 'markdown' or 'json'")

    lines = [
        f"# {session.title}",
        "",
        f"_{session.provider or '?'} · {session.model or 'default'} · "
        f"{session.mode} mode · {session.created_at}_",
        "",
    ]
    for turn in data:
        if turn["user"]:
            lines += ["## Question", "", turn["user"]["content"], ""]
        for step in turn["steps"]:
            args = json.dumps(step["arguments"], ensure_ascii=False)
            lines.append(f"- 🔧 `{step['name']}` {args}{' (error)' if step['is_error'] else ''}")
        if turn["steps"]:
            lines.append("")
        answer = turn["answer"]
        if answer:
            lines += ["## Answer", "", answer["content"], ""]
            if answer.get("citations"):
                lines.append("**Sources**")
                lines.append("")
                for c in answer["citations"]:
                    title = c.get("page_title") or c.get("source_url")
                    lines.append(f"{c['marker']}. [{title}]({c.get('source_url')})")
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"
