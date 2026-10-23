"use client";
// Apache ECharts is the single chart library (UX-005). Loaded lazily (see chart.tsx) so it is only downloaded by
// screens that draw charts. The chart is created once; a theme change arrives as a rebuilt option (pages build options
// from the theme's tokens, useChartTheme in chart.tsx), applied in place with the user's zoom window kept (audit S17).
// Re-creating the chart on every theme switch cost ~240 ms of interaction delay on a throttled phone (UX-011).
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

export default function ChartImpl({ option, onEvents }: {
  option: EChartsCoreOption; onEvents?: Record<string, (params: unknown) => void>;
}) {
  const el = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);
  const zoomed = useRef<{ start: number; end: number }[] | null>(null);
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    if (!el.current) return;
    const chart = echarts.init(el.current, undefined, { renderer: "canvas" });
    inst.current = chart;
    (el.current as HTMLDivElement & { __chart?: echarts.ECharts }).__chart = chart;   // read by the e2e theme test
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el.current);
    return () => { ro.disconnect(); chart.dispose(); inst.current = null; };
  }, []);

  useEffect(() => {
    const chart = inst.current;
    if (!chart) return;
    // keep the user's zoom window when the option is rebuilt (new colours, refreshed data): notMerge would reset it
    const live = ((chart.getOption()?.dataZoom ?? []) as { start?: number; end?: number }[])
      .map((z) => ({ start: z.start ?? 0, end: z.end ?? 100 }));
    if (!zoomed.current && live.some((z) => z.start > 0 || z.end < 100)) zoomed.current = live;
    // reduced motion (Phase 4B): charts appear in their final state instead of growing in for a second
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    chart.setOption(still ? { ...option, animation: false } : option, { notMerge: true });
    if (zoomed.current) {
      zoomed.current.forEach((z, i) => chart.dispatchAction({ type: "dataZoom", dataZoomIndex: i, start: z.start, end: z.end }));
      zoomed.current = null;     // re-applied once after the option was replaced
    }
    const handlers = Object.entries(onEvents ?? {});
    handlers.forEach(([ev, fn]) => chart.on(ev, fn));
    return () => { handlers.forEach(([ev, fn]) => chart.off(ev, fn)); };
  }, [option, onEvents]);

  return <div ref={el} className="size-full" data-chart-theme={resolvedTheme} />;
}
