// Chart colours come from the CSS tokens so both themes stay truthful. Kept free of any chart-library import so
// pages and the 3D view can use it without pulling ECharts into their bundle.
import type { EChartsCoreOption } from "echarts/core";

export function token(name: string) {
  if (typeof window === "undefined") return "#888";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

export function baseOption(): EChartsCoreOption {
  const ink = token("--ink"), muted = token("--muted"), line = token("--line");
  return {
    aria: { enabled: true },
    textStyle: { fontFamily: "var(--font-hanken), sans-serif", color: ink },
    grid: { left: 52, right: 20, top: 36, bottom: 56 },
    tooltip: { trigger: "axis", backgroundColor: token("--surface"), borderColor: line, textStyle: { color: ink },
      valueFormatter: (v: unknown) => (typeof v === "number" ? v.toLocaleString("en-GB", { maximumFractionDigits: 1 }) : String(v)) },
    // one line that scrolls when it does not fit: a wrapped legend ran into the axis title and labels on a phone
    legend: { type: "scroll", top: 4, textStyle: { color: muted }, pageIconColor: muted, pageTextStyle: { color: muted } },
    xAxis: { axisLine: { lineStyle: { color: line } }, axisLabel: { color: muted }, splitLine: { show: false } },
    yAxis: { axisLine: { lineStyle: { color: line } }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: line } } },
  };
}
