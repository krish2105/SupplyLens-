"use client";
import { Crash } from "@/components/crash";

// Inside the app shell: navigation, workspace switcher and sign-out stay usable when one screen fails (P2-FE-04).
export default function ScreenError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <Crash error={error} reset={reset} inShell />;
}
