import type { ChartAnnotation } from '../../lib/api';
export interface Note { price: number; text: string; color: string }
export interface Rect { x: number; y: number; w: number; h: number }
export function intersects(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}
/** Display aliases only. Original recorded annotation labels remain untouched. */
export function referenceNotes(annotations: ChartAnnotation[]): Note[] {
  const notes = new Map<number, Note>();
  for (const a of annotations) {
    if (a.type !== 'hline' || a.price == null || !Number.isFinite(a.price)) continue;
    const label = a.label;
    const text = /Stock stop|Setup invalidation/i.test(label) ? 'Idea breaks here'
      : /Stock entry reference|Entry trigger/i.test(label) ? 'Entry ref.'
      : /Stock target|Underlying target/i.test(label) ? 'Target ref.'
      : /Prior low.*support/i.test(label) ? 'Prior support'
      : /Prior high.*resistance/i.test(label) ? 'Prior resistance'
      : label.split('|')[0].trim();
    const priority = /^(Idea breaks here|Entry ref\.|Target ref\.)$/.test(text);
    if (!notes.has(a.price) || priority) notes.set(a.price, { price: a.price, text, color: a.color });
  }
  return [...notes.values()].sort((a,b) => Number(/ref\.|Idea breaks/.test(b.text)) - Number(/ref\.|Idea breaks/.test(a.text)));
}
/** Never place text over candles, trade-marker lanes, or another note.
 * Dense views omit a note rather than cover prices; recorded details remain available. */
export function placeNote(width: number, height: number, y: number, textWidth: number, obstacles: Rect[]): Rect | null {
  const w = Math.ceil(textWidth) + 12, h = 30;
  if (w > width - 24 || y < 0 || y > height) return null;
  for (let distance = 0; distance < height; distance += 18) {
    for (const top of [y - 40 - distance, y + 14 + distance]) {
      if (top < 36 || top + h > height - 30) continue;
      for (let x = 14; x + w < width - 8; x += 24) {
        const rect = { x, y: top, w, h };
        if (!obstacles.some(o => intersects(rect, o))) return rect;
      }
    }
  }
  return null;
}
