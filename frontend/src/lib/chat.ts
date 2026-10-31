/**
 * One chat turn as the UI renders it -- whether it is streaming right now or
 * was loaded from history -- and the hook that streams new turns.
 *
 * The harness streams text per model step. Text from a step that went on to
 * call tools is narration ("let me search…"), not the answer, so it is folded
 * into the reasoning; only the last step's text is shown as the answer.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { API_BASE, api } from "./api";
import { streamSse } from "./sse";
import type {
  Grounding,
  Mode,
  SourceCitation,
  ThinkingSetting,
  ToolStep,
  TraceEntry,
  Turn,
  Usage,
} from "./types";

export interface TurnModel {
  key: string;
  turnId?: string;
  question: string;
  reasoning: string;
  reasoningMs?: number;
  tools: ToolStep[];
  answer: string;
  citations: SourceCitation[];
  grounding?: Grounding | null;
  followups: string[];
  notices: string[];
  error?: string;
  messageId?: string;
  feedback: -1 | 0 | 1;
  trace: TraceEntry[];
  usage?: Usage | null;
  model?: string | null;
  mode?: Mode;
  elapsedMs?: number | null;
  streaming: boolean;
  phase: "searching" | "thinking" | "writing" | "done";
  cancelled?: boolean;
}

export function fromStored(turn: Turn): TurnModel {
  const a = turn.answer;
  return {
    key: turn.turn_id,
    turnId: turn.turn_id,
    question: turn.user?.content ?? "",
    reasoning: a?.thinking ?? "",
    tools: turn.steps.map((s) => ({ ...s, done: true })),
    answer: a?.content ?? "",
    citations: a?.citations ?? [],
    grounding: a?.grounding,
    followups: a?.followups ?? [],
    notices: [],
    messageId: a?.id,
    feedback: a?.feedback ?? 0,
    trace: a?.trace ?? [],
    usage: a?.usage,
    model: a?.model,
    elapsedMs: a?.elapsed_ms,
    streaming: false,
    phase: "done",
    cancelled: a?.trace?.some((t) => t.kind === "cancelled"),
  };
}

export interface SendOptions {
  prompt: string;
  replaceTurnId?: string;
  mode?: Mode;
  provider?: string;
  model?: string;
  thinking?: ThinkingSetting;
}

interface StepState {
  text: string;
  hasTools: boolean;
}

/** Streams turns for one session; finished turns are re-read from the server. */
export function useChatStream(sessionId: string | undefined) {
  const queryClient = useQueryClient();
  const [live, setLive] = useState<TurnModel | null>(null);
  const [replacing, setReplacing] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), [sessionId]);

  const send = useCallback(
    async (opts: SendOptions) => {
      if (!sessionId || abortRef.current) return;
      const ac = new AbortController();
      abortRef.current = ac;
      setReplacing(opts.replaceTurnId ?? null);

      const steps = new Map<number, StepState>();
      let current = 0;
      let thinking = "";
      let thinkingStarted: number | null = null;
      let reasoningMs: number | undefined;

      let model: TurnModel = {
        key: `live-${Date.now()}`,
        question: opts.prompt,
        reasoning: "",
        tools: [],
        answer: "",
        citations: [],
        followups: [],
        notices: [],
        feedback: 0,
        trace: [],
        streaming: true,
        phase: "searching",
      };
      const commit = (patch: Partial<TurnModel>) => {
        model = { ...model, ...patch };
        setLive(model);
      };
      const narration = () =>
        [...steps.entries()]
          .filter(([, s]) => s.hasTools && s.text.trim())
          .map(([, s]) => s.text.trim())
          .join("\n\n");
      const reasoningText = () => [thinking.trim(), narration()].filter(Boolean).join("\n\n");
      const answerText = () => {
        const s = steps.get(current);
        return s && !s.hasTools ? s.text : "";
      };
      commit({});

      try {
        for await (const msg of streamSse(
          `${API_BASE}/sessions/${sessionId}/chat/stream`,
          {
            method: "POST",
            body: JSON.stringify({
              prompt: opts.prompt,
              replace_turn_id: opts.replaceTurnId,
              mode: opts.mode,
              provider: opts.provider,
              model: opts.model,
              thinking: opts.thinking,
            }),
          },
          ac.signal,
        )) {
          const d = msg.data as Record<string, any>;
          switch (msg.event) {
            case "turn":
              commit({ turnId: d.turn_id, mode: d.mode, model: d.model });
              break;
            case "title":
              queryClient.invalidateQueries({ queryKey: ["sessions"] });
              queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
              break;
            case "notice":
              commit({ notices: [...model.notices, d.message] });
              break;
            case "step":
              current = d.index;
              steps.set(current, { text: "", hasTools: false });
              break;
            case "thinking":
              thinkingStarted ??= performance.now();
              thinking += d.t;
              commit({ reasoning: reasoningText(), phase: "thinking" });
              break;
            case "token": {
              const s = steps.get(d.step ?? current) ?? { text: "", hasTools: false };
              s.text += d.t;
              steps.set(d.step ?? current, s);
              if (thinkingStarted !== null && reasoningMs === undefined) {
                reasoningMs = performance.now() - thinkingStarted;
              }
              commit({ answer: answerText(), reasoningMs, phase: "writing" });
              break;
            }
            case "tool_call": {
              const s = steps.get(d.step ?? current) ?? { text: "", hasTools: false };
              s.hasTools = true;
              steps.set(d.step ?? current, s);
              commit({
                tools: [...model.tools, { id: d.id, name: d.name, arguments: d.arguments, is_error: false, elapsed_ms: null }],
                answer: answerText(),
                reasoning: reasoningText(),
                phase: "searching",
              });
              break;
            }
            case "tool_result":
              commit({
                tools: model.tools.map((t) =>
                  t.id === d.id ? { ...t, done: true, is_error: d.is_error, elapsed_ms: d.elapsed_ms, preview: d.preview } : t,
                ),
              });
              break;
            case "sources":
              commit({ citations: d.citations ?? [] });
              break;
            case "usage":
              commit({ usage: d as Usage });
              break;
            case "answer":
              if (thinkingStarted !== null && reasoningMs === undefined) {
                reasoningMs = performance.now() - thinkingStarted;
              }
              commit({ answer: d.content, citations: d.citations, messageId: d.message_id, reasoningMs, phase: "done" });
              break;
            case "grounding":
              commit({ grounding: d as Grounding });
              break;
            case "followups":
              commit({ followups: d.questions ?? [] });
              break;
            case "done":
              commit({ streaming: false, phase: "done", elapsedMs: d.elapsed_ms, cancelled: d.cancelled, model: d.model });
              break;
            case "error":
              commit({ streaming: false, phase: "done", error: String(d.message ?? "Something went wrong.") });
              break;
          }
        }
      } catch (err) {
        if (!ac.signal.aborted) {
          commit({ streaming: false, phase: "done", error: err instanceof Error ? err.message : String(err) });
        }
      } finally {
        abortRef.current = null;
        await queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
        queryClient.invalidateQueries({ queryKey: ["sessions"] });
        // Keep an errored turn on screen; a finished one now lives in history.
        if (!model.error) setLive(null);
        setReplacing(null);
      }
    },
    [sessionId, queryClient],
  );

  const stop = useCallback(() => {
    if (sessionId) api.cancelSession(sessionId).catch(() => {});
  }, [sessionId]);

  const dismissError = useCallback(() => setLive(null), []);

  return { live, replacing, send, stop, dismissError, busy: !!live?.streaming };
}
