import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cleanSnippet, linkCitations } from "../../lib/citations";
import type { SourceCitation } from "../../lib/types";

function hostPath(url: string): string {
  try {
    const u = new URL(url);
    return `${u.host}${u.pathname === "/" ? "" : u.pathname}`;
  } catch {
    return url;
  }
}

function Cite({
  marker,
  citation,
  active,
  onPick,
}: {
  marker: number;
  citation?: SourceCitation;
  active: boolean;
  onPick: (marker: number) => void;
}) {
  if (!citation) {
    return (
      <span className="cite cite-missing" title={`No source numbered ${marker} was retrieved`}>
        {marker}
      </span>
    );
  }
  return (
    <span className="group relative inline">
      <button
        type="button"
        className="cite"
        data-active={active}
        onClick={() => onPick(marker)}
        aria-label={`Source ${marker}: ${citation.page_title || citation.source_url}`}
      >
        {marker}
      </button>
      {/* Hover preview: the passage itself, so checking a claim is one glance. */}
      <span
        role="tooltip"
        className="pointer-events-none invisible absolute bottom-full left-1/2 z-30 mb-2 w-72 -translate-x-1/2 rounded-lg border border-line bg-raised p-3 text-left font-sans text-[13px] leading-snug text-body opacity-0 shadow-[0_12px_32px_-12px_rgb(15_20_30/0.3)] transition-opacity group-hover:visible group-hover:opacity-100"
      >
        <span className="block font-semibold text-ink">{citation.page_title || hostPath(citation.source_url)}</span>
        {citation.heading && <span className="block text-muted">{citation.heading}</span>}
        <span className="mt-1.5 line-clamp-4 block">{cleanSnippet(citation.snippet)}</span>
        <span className="mt-1.5 block truncate text-faint">{hostPath(citation.source_url)}</span>
      </span>
    </span>
  );
}

export const Answer = memo(function Answer({
  text,
  citations,
  activeMarker,
  onPick,
  streaming,
}: {
  text: string;
  citations: SourceCitation[];
  activeMarker?: number | null;
  onPick: (marker: number) => void;
  streaming?: boolean;
}) {
  const byMarker = new Map(citations.map((c) => [c.marker, c]));
  return (
    <div className={streaming ? "reading is-streaming" : "reading"}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const match = href?.match(/^#cite-(\d+)$/);
            if (match) {
              const marker = Number(match[1]);
              return (
                <Cite
                  marker={marker}
                  citation={byMarker.get(marker)}
                  active={activeMarker === marker}
                  onPick={onPick}
                />
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            );
          },
        }}
      >
        {linkCitations(text)}
      </ReactMarkdown>
    </div>
  );
});
