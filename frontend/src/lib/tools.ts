import { FileText, GitCompare, Globe, ListTree, Plug, Search, type LucideIcon } from "lucide-react";
import type { ToolStep } from "./types";

function quoted(value: unknown): string {
  const text = String(value ?? "");
  return `“${text.length > 60 ? text.slice(0, 59) + "…" : text}”`;
}

function shortUrl(value: unknown): string {
  try {
    const u = new URL(String(value));
    return `${u.host}${u.pathname === "/" ? "" : u.pathname}`;
  } catch {
    return String(value ?? "");
  }
}

/** Say what a tool did in plain words instead of showing its name. */
export function describeTool(step: Pick<ToolStep, "name" | "arguments">): { icon: LucideIcon; text: string } {
  const a = step.arguments ?? {};
  if (step.name.startsWith("mcp__")) {
    const [, server, tool] = step.name.split("__");
    return { icon: Plug, text: `Used ${tool?.replace(/_/g, " ")} from ${server}` };
  }
  switch (step.name) {
    case "search_site":
      return { icon: Search, text: `Searched ${quoted(a.query)}${a.workspace ? ` in ${a.workspace}` : ""}` };
    case "read_page":
      return { icon: FileText, text: `Read ${shortUrl(a.url)}` };
    case "list_pages":
      return { icon: ListTree, text: a.contains ? `Listed pages about ${quoted(a.contains)}` : "Listed the site’s pages" };
    case "list_workspaces":
      return { icon: ListTree, text: "Checked which sites are available" };
    case "compare_retrieval":
      return { icon: GitCompare, text: `Compared search strategies for ${quoted(a.query)}` };
    case "fetch_url":
      return { icon: Globe, text: `Fetched ${shortUrl(a.url)} live` };
    default:
      return { icon: Plug, text: step.name.replace(/_/g, " ") };
  }
}
