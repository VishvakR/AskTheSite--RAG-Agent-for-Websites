/** Chunk text without markdown heading marks, for previews. */
export function cleanSnippet(text: string): string {
  return text.replace(/(^|\s)#{1,6}\s+/g, "$1").replace(/\s+/g, " ").trim();
}

const CODE = /(```[\s\S]*?(?:```|$)|`[^`\n]*`)/g;
const MARKER = /\[(\d{1,3})\](?!\()/g;

/**
 * Turn inline `[3]` markers into links the renderer can recognise, without
 * touching code spans or fenced blocks (where `[3]` is usually an index).
 */
export function linkCitations(markdown: string): string {
  return markdown
    .split(CODE)
    .map((part, i) => (i % 2 === 1 ? part : part.replace(MARKER, "[$1](#cite-$1)")))
    .join("");
}
