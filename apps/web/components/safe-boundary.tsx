"use client";
import { Component, type ReactNode } from "react";

/** Keeps a failing shell widget (decision clock, command palette) from taking the whole app down with it: the widget is
 *  replaced by a one-line note and every screen stays usable (P2-FE-04). */
export class SafeBoundary extends Component<{ name: string; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: unknown) { console.error(error); }
  render() {
    if (this.state.failed) return <p role="status" className="px-4 py-1 text-xs text-muted md:px-6">The {this.props.name} could not be shown; the rest of the app works.</p>;
    return this.props.children;
  }
}
