"use client";
import dynamic from "next/dynamic";
import type { EChartsCoreOption } from "echarts/core";

export { baseOption, token } from "./chart-theme";

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
