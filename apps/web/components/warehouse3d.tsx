"use client";
// Schematic 3D warehouse (UX-005). Each rack is a real SKU-location row: height encodes
// days of cover (capped at 60), colour encodes the same health status as the table.
// frameloop="demand" means nothing renders while idle; no auto-rotation.
import { Canvas, invalidate, type ThreeEvent } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "next-themes";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { Crosshair, RotateCcw, X } from "lucide-react";
import type { InventoryItem } from "@/lib/queries";
import { token } from "./chart";
import { Button } from "./ui";
import { int, num } from "@/lib/format";

const MAX_COVER = 60;
const MAX_H = 4.2;

function healthColor(h: string) {
  return h === "shortage_risk" ? token("--danger") : h === "excess" ? token("--risk") : h === "healthy" ? token("--accent") : token("--muted");
}

export function webglAvailable() {
  try {
    const c = document.createElement("canvas");
    return !!(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl")));
  } catch { return false; }
}

function Rack({ item, selected, onSelect, colors }: { item: InventoryItem; selected: boolean; onSelect: (s: string) => void; colors: Record<string, string> }) {
  const cover = item.days_of_cover == null ? 0 : Math.min(item.days_of_cover, MAX_COVER);
  const h = Math.max(0.12, (cover / MAX_COVER) * MAX_H);
  const [hover, setHover] = useState(false);
  const color = colors[item.health] ?? colors.default;
  return (
    <group position={[item.x ?? 0, 0, item.z ?? 0]}>
      {/* rack frame */}
      <mesh position={[0, MAX_H / 2, 0]}>
        <boxGeometry args={[1.7, MAX_H, 1.1]} />
        <meshStandardMaterial color={colors.frame} transparent opacity={selected ? 0.35 : 0.12} wireframe={false} />
      </mesh>
      {/* stock column */}
      <mesh position={[0, h / 2, 0]} castShadow
        onClick={(e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); onSelect(item.sku_id); }}
        onPointerOver={(e) => { e.stopPropagation(); setHover(true); document.body.style.cursor = "pointer"; invalidate(); }}
        onPointerOut={() => { setHover(false); document.body.style.cursor = ""; invalidate(); }}>
        <boxGeometry args={[1.4, h, 0.85]} />
        <meshStandardMaterial color={color} emissive={selected ? color : "#000000"} emissiveIntensity={selected ? 0.45 : 0}
          roughness={0.55} metalness={0.05} />
      </mesh>
      {(selected || hover) && (
        <Html position={[0, MAX_H + 0.5, 0]} center distanceFactor={14} zIndexRange={[20, 0]}>
          <div className="pointer-events-none whitespace-nowrap rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs shadow-lg">
            <div className="num font-semibold">{item.sku_id} · slot {item.slot_id}</div>
            <div className="text-muted">{item.description.slice(0, 32)}</div>
            <div className="num">{int(item.available)} {item.unit} available · {item.days_of_cover == null ? "no sales data" : `${num(item.days_of_cover)} d cover`}</div>
          </div>
        </Html>
      )}
    </group>
  );
}

export default function Warehouse3D({ items, selected, onSelect, height = 460 }: {
  items: InventoryItem[]; selected: string | null; onSelect: (sku: string | null) => void; height?: number;
}) {
  const { resolvedTheme } = useTheme();
  const controls = useRef<OrbitControlsImpl | null>(null);
  const placed = items.filter((i) => i.x != null && i.z != null);
  const center = useMemo(() => {
    if (!placed.length) return [0, 0, 0] as [number, number, number];
    const xs = placed.map((i) => i.x!), zs = placed.map((i) => i.z!);
    return [(Math.min(...xs) + Math.max(...xs)) / 2, 0, (Math.min(...zs) + Math.max(...zs)) / 2] as [number, number, number];
  }, [placed]);
  const colors = useMemo(() => ({
    shortage_risk: healthColor("shortage_risk"), excess: healthColor("excess"), healthy: healthColor("healthy"),
    default: healthColor("x"), frame: token("--line-strong"), floor: token("--bg-deep"), grid: token("--line"),
  }), [resolvedTheme]); // eslint-disable-line react-hooks/exhaustive-deps

  const home: [number, number, number] = [center[0] + 18, 20, center[2] + 26];
  function reset() {
    const c = controls.current;
    if (!c) return;
    c.object.position.set(...home);
    c.target.set(...center);
    c.update(); invalidate();
  }
  function focus() {
    const it = placed.find((i) => i.sku_id === selected);
    const c = controls.current;
    if (!it || !c) return;
    c.target.set(it.x!, 1.5, it.z!);
    c.object.position.set(it.x! + 6, 8, it.z! + 9);
    c.update(); invalidate();
  }
  useEffect(() => { invalidate(); }, [selected, resolvedTheme]);

  return (
    <div className="relative" style={{ height }}>
      <Canvas frameloop="demand" shadows dpr={[1, 1.75]} camera={{ position: home, fov: 40 }}
        onPointerMissed={() => onSelect(null)} aria-label="3D schematic warehouse">
        <color attach="background" args={[colors.floor]} />
        <ambientLight intensity={0.7} />
        <directionalLight position={[20, 30, 10]} intensity={1.1} castShadow />
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[center[0], -0.01, center[2]]} receiveShadow>
          <planeGeometry args={[80, 60]} />
          <meshStandardMaterial color={colors.floor} />
        </mesh>
        <gridHelper args={[80, 40, colors.grid, colors.grid]} position={[center[0], 0, center[2]]} />
        {placed.map((it) => (
          <Rack key={it.sku_id} item={it} selected={it.sku_id === selected} onSelect={onSelect} colors={colors} />
        ))}
        <OrbitControls ref={controls as never} target={center} makeDefault enableDamping={false} maxPolarAngle={Math.PI / 2.15}
          minDistance={6} maxDistance={80} onChange={() => invalidate()} />
      </Canvas>
      <div className="absolute left-3 top-3 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={reset}><RotateCcw className="size-3.5" aria-hidden /> Reset camera</Button>
        <Button size="sm" variant="outline" onClick={focus} disabled={!selected}><Crosshair className="size-3.5" aria-hidden /> Focus selected</Button>
        <Button size="sm" variant="outline" onClick={() => onSelect(null)} disabled={!selected}><X className="size-3.5" aria-hidden /> Clear selection</Button>
      </div>
      <div className="absolute bottom-3 left-3 rounded-lg border border-line bg-surface/90 px-3 py-2 text-[11px] text-muted">
        <span className="font-semibold text-ink">Schematic</span> — generated layout, not measured geometry. Column height = days of cover (max {MAX_COVER}).
        <div className="mt-1 flex flex-wrap gap-3">
          {[["shortage_risk", "Under 7 days"], ["healthy", "7–90 days"], ["excess", "Over 90 days"], ["x", "No sales data"]].map(([k, l]) => (
            <span key={k} className="inline-flex items-center gap-1"><span className="size-2.5 rounded-sm" style={{ background: healthColor(k!) }} />{l}</span>
          ))}
        </div>
      </div>
    </div>
  );
}
