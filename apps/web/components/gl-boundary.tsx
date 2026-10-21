"use client";
import { Component, type ReactNode } from "react";

/** Catches a failed WebGL renderer (context creation error, GPU reset) so the 2D floor plan can take over. */
export class GLBoundary extends Component<{ children: ReactNode; fallback: ReactNode; onError?: (e: Error) => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(e: Error) { this.props.onError?.(e); }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

export function GLNotice() {
  return (
    <p role="status" className="mx-4 mt-3 rounded-lg bg-risk-soft px-3 py-2 text-sm text-risk">
      The 3D view stopped working on this device. The 2D floor plan below shows the same records, and nothing else is affected.
    </p>
  );
}
