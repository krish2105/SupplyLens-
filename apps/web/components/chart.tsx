"use client";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import type { EChartsCoreOption } from "echarts/core";

export { baseOption, token } from "./chart-theme";

/** Add to the dependencies of every memoised chart option: options read colours from CSS tokens when built, so they
 *  must be rebuilt when the theme changes. */
export function useChartTheme() {
  const { resolvedTheme } = useTheme();
  const [applied, setApplied] = useState(resolvedTheme ?? "light");
  useEffect(() => {
    // next-themes swaps the <html> class in its own effect; read the tokens on the next frame, once the new class is in
    // place, or the rebuilt option would still carry the previous theme's colours
    const id = requestAnimationFrame(() => setApplied(resolvedTheme ?? "light"));
    return () => cancelAnimationFrame(id);
  }, [resolvedTheme]);
  return applied;
}

const Impl = dynamic(() => import("./chart-impl"), { ssr: false });

/** The container reserves the chart's height from the first paint (no layout shift) and carries its accessible name. */
export function Chart({ option, height = 320, label, onEvents }: {
  option: EChartsCoreOption; height?: number; label: string;
  onEvents?: Record<string, (params: any) => void>;
}) {
  return (
    <div role="img" aria-label={label} style={{ height }} className="w-full">
      <Impl option={option} onEvents={onEvents} />
    </div>
  );
}
