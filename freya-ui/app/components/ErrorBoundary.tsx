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
}

interface State {
  error: Error | null;
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
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
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
  }

  reset = () => this.setState({ error: null });

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
          style={{ color: "var(--accent-red, #ff2b3a)" }}
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
