/** Hypothetical long-spot sizing, with estimated round-trip fees and slippage. */
export function sizePracticeTrade(
  equity: number,
  cash: number,
  entry: number,
  stop: number,
  target: number,
  riskPercent: number,
  fee: number,
  slippage: number,
) {
  if (
    ![equity, cash, entry, stop, target, riskPercent, fee, slippage].every(
      Number.isFinite,
    ) ||
    equity <= 0 ||
    cash < 0 ||
    entry <= 0 ||
    stop <= 0 ||
    stop >= entry ||
    target <= entry ||
    riskPercent <= 0 ||
    riskPercent > 100 ||
    fee < 0 ||
    fee >= 1 ||
    slippage < 0 ||
    slippage >= 1
  )
    return null;
  const entryCost = entry * (1 + slippage) * (1 + fee),
    stopReturn = stop * (1 - slippage) * (1 - fee),
    targetReturn = target * (1 - slippage) * (1 - fee);
  const unitRisk = entryCost - stopReturn,
    budget = (equity * riskPercent) / 100;
  const units =
    Math.floor(Math.min(budget / unitRisk, cash / entryCost) * 1e8) / 1e8;
  return {
    budget,
    units,
    estimatedLoss: units * unitRisk,
    estimatedGain: units * (targetReturn - entryCost),
    ratio: (targetReturn - entryCost) / unitRisk,
    cashLimited: cash / entryCost < budget / unitRisk,
  };
}
export const RANGES = [
  { label: "1Y", seconds: 365 * 86400 },
  { label: "1W", seconds: 7 * 86400 },
  { label: "1D", seconds: 86400 },
  { label: "1h", seconds: 3600 },
  { label: "1m", seconds: 60 },
] as const;
export function visibleRange(
  times: number[],
  interval: number,
  seconds: number,
) {
  if (!times.length) return null;
  const end = times[times.length - 1] + interval;
  const start = end - seconds;
  const first = times.findIndex((t) => t + interval > start);
  return {
    from: Math.max(0, first === -1 ? times.length - 1 : first) - 0.5,
    to: times.length - 0.5,
    limited: times[0] > start,
  };
}
