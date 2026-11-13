import type { IChartApi, ISeriesApi, ISeriesPrimitive, IPrimitivePaneView, IPrimitivePaneRenderer, Time } from 'lightweight-charts';
import type { Bar, Trade } from '../../lib/api';
import { placeNote, type Note, type Rect } from './handwrittenLayout';
import { toEpochTime } from './zoneBands';

/** Native pane primitive redraws with the chart's own pan, zoom and price scale.
 * No autoscale overrides, independent clocks, or changes to candle data. */
export class HandwrittenNotes implements ISeriesPrimitive<Time> {
  private notes: Note[] = [];
  private bars: Bar[] = [];
  private trades: Trade[] = [];
  private requestUpdate = () => {};
  private view: IPrimitivePaneView;
  private chart: IChartApi;
  private candle: ISeriesApi<'Candlestick'>;
  constructor(chart: IChartApi, candle: ISeriesApi<'Candlestick'>) {
    this.chart = chart; this.candle = candle;
    const renderer: IPrimitivePaneRenderer = { draw: target => target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      const { width, height } = mediaSize;
      const scale = this.chart.timeScale();
      const obstacles: Rect[] = [];
      const projected = this.bars.map(b => ({ b, x: scale.timeToCoordinate(toEpochTime(b.time)) }));
      const visible = projected.filter(p => p.x != null && p.x >= -10 && p.x <= width + 10);
      const spacing = visible.length > 1 ? Math.abs(visible[1].x! - visible[0].x!) : 8;
      for (const {b,x} of visible) {
        const high = this.candle.priceToCoordinate(b.high), low = this.candle.priceToCoordinate(b.low);
        if (high != null && low != null) obstacles.push({ x: x! - spacing / 2 - 5, y: Math.min(high,low) - 8, w: spacing + 10, h: Math.abs(low-high) + 16 });
      }
      // Reserve complete vertical lanes around Buy and Sell. Even stacked native
      // markers stay readable when the price scale or candle interval changes.
      for (const trade of this.trades) for (const iso of [trade.entry_time, trade.exit_time]) {
        if (!iso) continue;
        const time = Number(toEpochTime(iso));
        let bar = this.bars[0];
        for (const b of this.bars) { if (Number(toEpochTime(b.time)) <= time) bar = b; else break; }
        const x = bar && scale.timeToCoordinate(toEpochTime(bar.time));
        if (x != null) obstacles.push({ x: x - 45, y: 0, w: 90, h: height });
      }
      ctx.save();
      ctx.font = '600 22px CeloHand, "Bradley Hand", "Segoe Print", cursive';
      ctx.textBaseline = 'middle';
      for (const note of this.notes) {
        const y = this.candle.priceToCoordinate(note.price);
        if (y == null || y < 0 || y > height) continue;
        const text = `${note.text}  $${note.price.toFixed(2)}`;
        const rect = placeNote(width, height, y, ctx.measureText(text).width, obstacles);
        if (!rect) continue;
        obstacles.push({ x: rect.x - 5, y: rect.y - 5, w: rect.w + 10, h: rect.h + 10 });
        ctx.fillStyle = note.color;
        ctx.fillText(text, rect.x + 6, rect.y + 15);
        // The short leader ends at the exact price. It is not a trade signal.
        ctx.strokeStyle = note.color;
        ctx.lineWidth = 1.2;
        const x = rect.x + rect.w - 8, start = rect.y > y ? rect.y : rect.y + rect.h;
        ctx.beginPath(); ctx.moveTo(x - 15, start); ctx.quadraticCurveTo(x + 3, start, x, y); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(x - 4, y + (start > y ? 5 : -5)); ctx.lineTo(x,y); ctx.lineTo(x + 4,y + (start > y ? 5 : -5)); ctx.stroke();
      }
      ctx.restore();
    }) };
    this.view = { zOrder: () => 'normal', renderer: () => renderer };
  }
  attached({ requestUpdate }: Parameters<NonNullable<ISeriesPrimitive<Time>['attached']>>[0]) {
    this.requestUpdate = requestUpdate;
    document.fonts.load('600 22px CeloHand').then(() => this.requestUpdate());
  }
  detached() { this.requestUpdate = () => {}; }
  paneViews() { return [this.view]; }
  set(notes: Note[], bars: Bar[], trades: Trade[]) { this.notes = notes; this.bars = bars; this.trades = trades; this.requestUpdate(); }
}
