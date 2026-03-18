import { Component } from "react";
import type { ReactNode, ErrorInfo } from "react";

interface Props {
  children: ReactNode;
  label?: string;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[ErrorBoundary:${this.props.label ?? "panel"}]`, error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="cell" style={{ flex: 1 }}>
          <div className="cell-head" style={{ color: "var(--text-danger, #f87171)" }}>
            {this.props.label ?? "Panel"} — crashed
          </div>
          <div className="cell-body" style={{ padding: 16, fontSize: 11, color: "var(--text-tertiary)" }}>
            <div style={{ marginBottom: 8, color: "var(--text-secondary, #e5e7eb)" }}>
              {this.state.error.message}
            </div>
            <button
              className="btn"
              style={{ fontSize: 10, padding: "2px 8px" }}
              onClick={() => this.setState({ error: null })}
            >
              Retry
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
