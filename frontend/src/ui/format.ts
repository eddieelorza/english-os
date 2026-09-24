/* Exact counts, right-aligned like hand-timed tracklists (DESIGN rule 3) —
   never rounded. It lived in VocabularyPage and fourteen files imported it
   from there; a number format is apparatus, not a page's business. */
export function fmt(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString('en-US')
}
