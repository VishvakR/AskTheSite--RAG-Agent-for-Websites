import { useEffect, useRef, useState } from "react";
import { API_BASE } from "./api";
import { streamSse } from "./sse";
import type { Job } from "./types";

/**
 * Subscribe to a job's progress stream.
 *
 * The server replays the job's current state on connect, so mounting this
 * after a job has already finished still yields a correct final value.
 */
export function useJobProgress(jobId: string | null) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      setError(null);
      return;
    }

    const ac = new AbortController();
    controller.current = ac;
    let cancelled = false;

    (async () => {
      try {
        for await (const message of streamSse(
          `${API_BASE}/jobs/${jobId}/events`,
          undefined,
          ac.signal,
        )) {
          if (cancelled) return;
          if (message.event === "progress") setJob(message.data as Job);
          else if (message.event === "end") return;
        }
      } catch (err) {
        if (!cancelled && !ac.signal.aborted) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    })();

    return () => {
      cancelled = true;
      ac.abort();
    };
  }, [jobId]);

  return { job, error, done: job ? ["succeeded", "failed", "cancelled"].includes(job.status) : false };
}
