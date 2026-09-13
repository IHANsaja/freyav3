export interface Candle {
  id: string;
  time: number;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
}
export interface Fill {
  order_id: string;
  time: number;
  side: string;
  quantity: string;
  price: string;
  fee: string;
  ambiguous: boolean;
}
export interface Session {
  environment?: string;
  feed_stale?: boolean;
  id: string;
  symbol: string;
  interval: number;
  mode: string;
  revision: number;
  sequence: number;
  source: string;
  cash: string;
  quantity: string;
  equity: string;
  fees: string;
  drawdown: string;
  sample_size: number;
  reserved_cash: string;
  reserved_quantity: string;
  finished: boolean;
  fee: string;
  slippage: string;
  candles: Candle[];
  indicators: {
    time: number;
    ema: number | null;
    rsi: number | null;
    atr: number | null;
  }[];
  flags: string[];
  thesis: { text: string; invalidation: string } | null;
  orders: {
    id: string;
    side: string;
    kind: string;
    status: string;
    quantity: string;
  }[];
  fills: Fill[];
}
export interface Report {
  id: string;
  revision: number;
  snapshot_id: string;
  as_of: number;
  provider: string;
  status: string;
  error: string | null;
  stale: boolean;
  veto: boolean;
  image_levels_approximate: boolean;
  prompt_version: string;
  usage: { model: string; tokens: number | null; cost_usd: string | null };
  stages: {
    name: string;
    status: string;
    finding: string;
    duration_ms: number;
    evidence: string[];
  }[];
  analysis: {
    observations: { text: string; evidence: string[] }[];
    zones: { low: string; high: string; kind: string; evidence: string[] }[];
    bullish: string;
    bearish: string;
    invalidation: string;
    lesson: string;
  } | null;
}
