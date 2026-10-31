import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { api } from "../lib/api";
import { Button, ErrorNote, Spinner, cn } from "./ui";
import { useShell } from "../lib/shell";

const STATUS_TEXT: Record<string, string> = {
  ready: "text-good",
  failed: "text-bad",
  empty: "text-faint",
};

export default function WorkspacesHome() {
  const { openAddSite } = useShell();
  const { data, isLoading, error } = useQuery({
    queryKey: ["workspaces"],
    queryFn: api.listWorkspaces,
    refetchInterval: 6_000,
  });

  return (
    <div className="mx-auto max-w-4xl px-5 pt-14 pb-16 md:pt-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-serif text-[1.9rem] font-semibold text-ink">Sites</h1>
          <p className="mt-1 max-w-prose text-[14.5px] text-muted">
            Each site is crawled once and indexed on this machine. Chats can search one site, several, or all of them.
          </p>
        </div>
        <Button variant="primary" onClick={openAddSite}>
          <Plus size={15} />
          Add a site
        </Button>
      </div>

      {isLoading && <div className="py-16"><Spinner /></div>}
      {error != null && <div className="mt-8"><ErrorNote error={error} /></div>}

      {data && data.length === 0 && (
        <p className="mt-12 text-[15px] text-muted">
          Nothing indexed yet.{" "}
          <button type="button" onClick={openAddSite} className="text-brand hover:underline">
            Add a docs site
          </button>{" "}
          to start asking it questions.
        </p>
      )}

      {data && data.length > 0 && (
        <table className="mt-8 w-full text-left text-[14px]">
          <thead className="border-b border-line text-[13px] text-muted">
            <tr>
              <th className="py-2 pr-4 font-medium">Site</th>
              <th className="hidden py-2 pr-4 font-medium sm:table-cell">Pages</th>
              <th className="hidden py-2 pr-4 font-medium sm:table-cell">Passages</th>
              <th className="py-2 pr-4 font-medium">Status</th>
              <th className="py-2 font-medium"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {data.map((w) => (
              <tr key={w.id}>
                <td className="max-w-0 py-3 pr-4">
                  <Link to={`/sites/${w.id}/lab`} className="block truncate font-medium text-ink hover:text-brand">
                    {w.name}
                  </Link>
                  <span className="block truncate text-[12.5px] text-faint">{w.seed_url}</span>
                </td>
                <td className="hidden py-3 pr-4 tabular-nums sm:table-cell">{w.page_count}</td>
                <td className="hidden py-3 pr-4 tabular-nums sm:table-cell">{w.chunk_count}</td>
                <td className={cn("py-3 pr-4", STATUS_TEXT[w.status] ?? "text-warn")}>{w.status}</td>
                <td className="py-3 text-right whitespace-nowrap">
                  <Link
                    to={`/?site=${w.id}`}
                    aria-disabled={!w.chunk_count}
                    className={cn("rounded-md px-2.5 py-1 text-[13.5px] text-brand hover:bg-brand-soft", !w.chunk_count && "pointer-events-none opacity-40")}
                  >
                    Ask
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
