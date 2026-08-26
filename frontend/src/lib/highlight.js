/**
 * Split body text into rendered segments, marking the passages that support a
 * selected summary sentence.
 *
 * The backend returns character offsets into the preprocessed body -- the same
 * string this component renders -- so no re-matching happens in the browser.
 * Doing the search client-side would risk highlighting a different passage than
 * the one the server verified, which would make the feature actively
 * misleading rather than merely imperfect.
 */

/**
 * @param {string} text  the body as rendered
 * @param {Array<{start:number,end:number}>} spans
 * @returns {Array<{text:string, highlighted:boolean}>}
 */
export function segment(text, spans) {
  if (!text) return [];
  const ranges = (spans || [])
    .filter((s) => Number.isFinite(s.start) && Number.isFinite(s.end) && s.end > s.start)
    .map((s) => ({ start: Math.max(0, s.start), end: Math.min(text.length, s.end) }))
    .sort((a, b) => a.start - b.start);

  if (ranges.length === 0) return [{ text, highlighted: false }];

  // Merge overlaps so a character is never wrapped twice.
  const merged = [ranges[0]];
  for (const range of ranges.slice(1)) {
    const last = merged[merged.length - 1];
    if (range.start <= last.end) last.end = Math.max(last.end, range.end);
    else merged.push(range);
  }

  const out = [];
  let cursor = 0;
  for (const { start, end } of merged) {
    if (start > cursor) out.push({ text: text.slice(cursor, start), highlighted: false });
    out.push({ text: text.slice(start, end), highlighted: true });
    cursor = end;
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor), highlighted: false });
  return out;
}

/** Renders a segment list back into paragraphs, preserving blank-line breaks. */
export function toParagraphs(segments) {
  const paragraphs = [[]];
  for (const seg of segments) {
    const pieces = seg.text.split("\n");
    pieces.forEach((piece, i) => {
      if (i > 0) paragraphs.push([]);
      if (piece) paragraphs[paragraphs.length - 1].push({ text: piece, highlighted: seg.highlighted });
    });
  }
  return paragraphs;
}
