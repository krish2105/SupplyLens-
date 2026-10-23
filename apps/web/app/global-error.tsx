"use client";
import "./globals.css";
import { Crash } from "@/components/crash";

// The root layout itself failed: this replaces it, so it brings its own <html> and <body> (P2-FE-04).
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en-GB">
      <body className="min-h-screen bg-bg text-ink"><Crash error={error} reset={reset} /></body>
    </html>
  );
}
