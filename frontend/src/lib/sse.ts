/**
 * Server-sent events over `fetch`.
 *
 * `EventSource` cannot issue POST requests or send a JSON body, so the chat
 * stream and the job progress stream are both parsed by hand from the response
 * body reader.
 */

export interface SseMessage {
  event: string;
  data: unknown;
}

function parseFrame(frame: string): SseMessage | null {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;

  const raw = dataLines.join("\n");
  try {
    return { event, data: JSON.parse(raw) };
  } catch {
    return { event, data: raw };
  }
}

/** Consume an SSE endpoint as an async iterable of parsed messages. */
export async function* streamSse(
  url: string,
  init?: RequestInit,
  signal?: AbortSignal,
): AsyncGenerator<SseMessage> {
  const res = await fetch(url, {
    ...init,
    signal,
    headers: {
      Accept: "text/event-stream",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(detail || `Stream failed (${res.status})`);
  }
  if (!res.body) throw new Error("Streaming is not supported by this browser");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Frames are separated by a blank line.
      let split: number;
      while ((split = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, split);
        buffer = buffer.slice(split + 2);
        const message = parseFrame(frame);
        if (message) yield message;
      }
    }
    const tail = parseFrame(buffer);
    if (tail) yield tail;
  } finally {
    reader.cancel().catch(() => {});
  }
}
