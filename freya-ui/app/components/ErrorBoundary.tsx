"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  /** What failed, for the log line and (optionally) the fallback copy. */
  label?: string;
  /** Custom fallback. If omitted, a themed default panel is shown. Receives the
   *  error and a reset callback so a fallback can offer "try again". */
  fallback?: (error: Error, reset: () => void) => ReactNode;
  /** Render nothing at all on error instead of a panel — for decorative
   *  subtrees (e.g. the WebGL scene) where a visible error box would be worse
   *  than silence. The surrounding UI keeps working regardless. */
  silent?: boolean;
  /** Recovery protocol: re-mount the subtree by itself after a failure, with
   *  backoff (2 s, 4 s, 8 s … up to 60 s), so a transient fault — a WebGL
   *  context loss, a malformed frame — heals without anyone clicking Retry.
   *  A subtree that stays healthy for 30 s resets the backoff. */
  autoRetry?: boolean;
  /** Give up auto-retrying after this many attempts in a row (default 8). */
  maxRetries?: number;
}

interface State {
  error: Error | null;
  attempt: number;
}

/**
 * Catches render/lifecycle errors in its subtree so one broken component can't
 * white-screen the whole dashboard — React unmounts the entire tree on an
 * uncaught error, and without a boundary anywhere that meant a single throw
 * (a malformed prop, a WebGL context loss, a bad shader) took down everything.
 *
 * Boundaries only catch errors during React rendering; event handlers, async
 * callbacks and the WebSocket loop throw outside that and are guarded at their
 * own call sites. This is the backstop for the rest.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, attempt: 0 };
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private healthyTimer: ReturnType<typeof setTimeout> | null = null;

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // console.warn, not console.error: keeps it out of the Next.js dev-overlay
    // issue count while still surfacing the failure and its component stack.
    console.warn(
      `[ErrorBoundary${this.props.label ? `:${this.props.label}` : ""}] caught:`,
      error,
      info.componentStack
    );
    if (this.healthyTimer) clearTimeout(this.healthyTimer);
    const { autoRetry, maxRetries = 8 } = this.props;
    if (!autoRetry || this.state.attempt >= maxRetries) return;
    const delay = Math.min(60_000, 2000 * 2 ** this.state.attempt);
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = setTimeout(() => {
      this.setState((s) => ({ error: null, attempt: s.attempt + 1 }));
    }, delay);
  }

  componentDidUpdate(_prev: Props, prevState: State) {
    // Came back from an error: if it stays up for 30 s, it's healthy again.
    if (prevState.error && !this.state.error && this.state.attempt > 0) {
      if (this.healthyTimer) clearTimeout(this.healthyTimer);
      this.healthyTimer = setTimeout(() => this.setState({ attempt: 0 }), 30_000);
    }
  }

  componentWillUnmount() {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    if (this.healthyTimer) clearTimeout(this.healthyTimer);
  }

  reset = () => this.setState({ error: null, attempt: 0 });

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    if (this.props.silent) return null;
    if (this.props.fallback) return this.props.fallback(error, this.reset);

    return (
      <div
        role="alert"
        className="m-4 p-4 border text-xs font-mono"
        style={{
          borderColor: "var(--accent-red-dim, #7a1f2b)",
          background: "rgba(18,10,11,0.6)",
          color: "var(--text-secondary, #b0a0a0)",
          borderRadius: "6px",
        }}
      >
        <div
          className="tracking-[0.15em] uppercase mb-2"
          style={{ color: "var(--accent-red, #22e0a0)" }}
        >
          {this.props.label ? `${this.props.label} error` : "Something went wrong"}
        </div>
        <p className="mb-3 leading-relaxed">
          This panel hit an error and was isolated so the rest of the dashboard keeps working.
        </p>
        <button
          onClick={this.reset}
          className="px-3 py-1.5 border transition-colors duration-200 uppercase tracking-wider"
          style={{ borderColor: "var(--panel-border, #3a2a2b)", color: "var(--text-secondary)" }}
        >
          Retry
        </button>
      </div>
    );
  }
}
