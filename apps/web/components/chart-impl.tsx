"use client";
// Apache ECharts is the single chart library (UX-005). Loaded lazily (see chart.tsx) so it is only downloaded by
// screens that draw charts. The chart re-initialises when the theme changes.
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
  option: EChartsCoreOption; onEvents?: Record<string, (params: any) => void>;
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

  return <div ref={el} className="size-full" />;
}
