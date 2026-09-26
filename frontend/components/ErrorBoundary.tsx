'use client';
import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  /** Shown in the message so you know which part of the app broke. */
  label: string;
  /** When this changes the boundary clears itself (e.g. the active tab). */
  resetKey?: string;
}

interface State { error: Error | null }

/**
 * A crash in one tab must not blank the whole terminal. This catches render errors for the
 * subtree, shows what broke, and lets the user retry — the sidebar, tabs and other data keep working.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[${this.props.label}] render error`, error, info.componentStack);
  }

  componentDidUpdate(prev: Props) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="m-4 rounded-lg border border-[#5a2020] bg-[#1f0a0a] p-4 text-sm">
        <div className="font-bold text-down">{this.props.label} hit an error</div>
        <p className="mt-1 text-xs text-dim">{this.state.error.message || 'Unexpected error'}</p>
        <button
          type="button"
          onClick={() => this.setState({ error: null })}
          className="mt-3 rounded-md border border-[#5a2020] bg-[#3a1414] px-3 py-1.5 text-xs font-semibold text-down"
        >
          Try again
        </button>
      </div>
    );
  }
}
