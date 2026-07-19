/**
 * indicators.ts — client-side technical indicator math.
 *
 * Single source of truth: TradingChart.tsx used to hand-calculate these while
 * KChart.tsx used klinecharts' built-in indicators (a different, unverified
 * formula) — meaning the same ticker could show different RSI/MACD values
 * depending on which page you were on. The new engine computes everything
 * once, here, and both live/replay/journal views read the same numbers.
 */

export function rollingMean(arr: number[], n: number): (number | null)[] {
  return arr.map((_, i) => {
    if (i < n - 1) return null;
    let sum = 0;
    for (let j = i - n + 1; j <= i; j++) sum += arr[j];
    return sum / n;
  });
}

/** EMA seeded with a simple average of the first `period` values. */
export function calcEMA(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(data.length).fill(null);
  if (data.length < period) return result;
  const k = 2 / (period + 1);
  let ema = 0;
  for (let i = 0; i < period; i++) ema += data[i];
  ema /= period;
  result[period - 1] = ema;
  for (let i = period; i < data.length; i++) {
    ema = data[i] * k + ema * (1 - k);
    result[i] = ema;
  }
  return result;
}

/** RSI with Wilder smoothing (the standard definition). */
export function calcRSI(closes: number[], period = 14): (number | null)[] {
  const result: (number | null)[] = new Array(closes.length).fill(null);
  if (closes.length < period + 1) return result;

  let avgGain = 0, avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const d = closes[i] - closes[i - 1];
    if (d > 0) avgGain += d; else avgLoss -= d;
  }
  avgGain /= period;
  avgLoss /= period;
  result[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);

  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    const gain = d > 0 ? d : 0;
    const loss = d < 0 ? -d : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    result[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return result;
}

export interface MACDData {
  macd: (number | null)[];
  signal: (number | null)[];
  hist: (number | null)[];
}

export function calcMACD(closes: number[], fast = 12, slow = 26, sig = 9): MACDData {
  const emaFast = calcEMA(closes, fast);
  const emaSlow = calcEMA(closes, slow);

  const macdLine: (number | null)[] = closes.map((_, i) => {
    const f = emaFast[i], s = emaSlow[i];
    return f != null && s != null ? f - s : null;
  });

  const signalLine: (number | null)[] = new Array(closes.length).fill(null);
  const histLine: (number | null)[] = new Array(closes.length).fill(null);

  const firstIdx = macdLine.findIndex((v) => v != null);
  if (firstIdx === -1 || firstIdx + sig > closes.length) {
    return { macd: macdLine, signal: signalLine, hist: histLine };
  }

  const seedSlice = macdLine.slice(firstIdx, firstIdx + sig) as number[];
  const sigK = 2 / (sig + 1);
  let sigEma = seedSlice.reduce((a, b) => a + b, 0) / sig;
  const seedEnd = firstIdx + sig - 1;
  signalLine[seedEnd] = sigEma;
  histLine[seedEnd] = (macdLine[seedEnd] ?? 0) - sigEma;

  for (let i = seedEnd + 1; i < closes.length; i++) {
    const m = macdLine[i];
    if (m == null) continue;
    sigEma = m * sigK + sigEma * (1 - sigK);
    signalLine[i] = sigEma;
    histLine[i] = m - sigEma;
  }

  return { macd: macdLine, signal: signalLine, hist: histLine };
}
