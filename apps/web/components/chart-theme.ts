// Chart colours come from the CSS tokens so both themes stay truthful. Kept free of any chart-library import so
// pages and the 3D view can use it without pulling ECharts into their bundle.
import { useEffect, useState } from "react";
import type { EChartsCoreOption } from "echarts/core";

export function token(name: string) {
  if (typeof window === "undefined") return "#888";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

/** Add to the dependencies of every memo that reads colours with token(): charts, the 3D view.
 *  token() reads CSS variables from <html>, and next-themes swaps the theme class there in its own effect, sometimes
 *  after the memo has already re-read the old theme's values. Reading on next-themes' resolvedTheme (or one frame after
 *  it, audit S17) still lost that race under load: the hosted 3D floor stayed dark in light theme (Phase 8 F1). So the
 *  value changes when the class on <html> has actually changed, and once more on the first frame after mount. */
export function useChartTheme() {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const html = document.documentElement;
    let last = html.className;
    const first = requestAnimationFrame(() => setVersion((n) => n + 1));
    const watch = new MutationObserver(() => {
      if (html.className === last) return;
      last = html.className;
      setVersion((n) => n + 1);
    });
    watch.observe(html, { attributes: true, attributeFilter: ["class"] });
    return () => { cancelAnimationFrame(first); watch.disconnect(); };
  }, []);
  return version;
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
