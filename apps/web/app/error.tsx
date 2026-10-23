"use client";
import { Crash } from "@/components/crash";

// Outside the app shell (sign-in, or the shell itself failing).
export default function RootError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <main className="min-h-screen bg-bg"><Crash error={error} reset={reset} /></main>;
}
