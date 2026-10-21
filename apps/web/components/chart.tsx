"use client";
// Apache ECharts is the single chart library (UX-005). Colours come from the CSS tokens so
// both themes stay truthful; the chart re-initialises when the theme changes.
import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, ScatterChart } from "echarts/charts";
import {
  AriaComponent, DataZoomComponent, GridComponent, LegendComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { useTheme } from "next-themes";
import type { EChartsCoreOption } from "echarts/core";

echarts.use([LineChart, BarChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent,
  MarkLineComponent, MarkAreaComponent, AriaComponent, CanvasRenderer]);

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
    legend: { top: 4, textStyle: { color: muted } },
    xAxis: { axisLine: { lineStyle: { color: line } }, axisLabel: { color: muted }, splitLine: { show: false } },
    yAxis: { axisLine: { lineStyle: { color: line } }, axisLabel: { color: muted }, splitLine: { lineStyle: { color: line } } },
  };
}

export function Chart({ option, height = 320, label, onEvents }: {
  option: EChartsCoreOption; height?: number; label: string;
  onEvents?: Record<string, (params: any) => void>;
}) {
  const el = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    if (!el.current) return;
    const chart = echarts.init(el.current, undefined, { renderer: "canvas" });
    inst.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el.current);
    return () => { ro.disconnect(); chart.dispose(); inst.current = null; };
  }, [resolvedTheme]);

  useEffect(() => {
    const chart = inst.current;
    if (!chart) return;
    chart.setOption(option, { notMerge: true });
    const handlers = Object.entries(onEvents ?? {});
    handlers.forEach(([ev, fn]) => chart.on(ev, fn));
    return () => { handlers.forEach(([ev, fn]) => chart.off(ev, fn)); };
  }, [option, onEvents, resolvedTheme]);

  return <div ref={el} role="img" aria-label={label} style={{ height }} className="w-full" />;
}
