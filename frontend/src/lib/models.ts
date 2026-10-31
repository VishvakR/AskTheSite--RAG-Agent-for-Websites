import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { ModelsResponse } from "./types";

export function useModels() {
  return useQuery({ queryKey: ["models"], queryFn: api.models, staleTime: 30_000 });
}

/** Resolve the label of the model a chat will actually use. */
export function modelLabel(models: ModelsResponse | undefined, provider: string | null, model: string | null): string {
  const p = provider ?? models?.default ?? null;
  const m = model ?? (p === models?.default ? models?.default_model : null) ?? null;
  const spec = models?.providers.find((x) => x.provider === p)?.specs.find((s) => s.id === m);
  return spec?.label ?? m ?? "Default model";
}
