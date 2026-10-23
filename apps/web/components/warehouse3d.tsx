"use client";
// Schematic 3D warehouse (UX-005). Each rack is a real SKU-location row: height encodes
// days of cover (capped at 60), colour encodes the same health status as the table.
// frameloop="demand" means nothing renders while idle; no auto-rotation.
import { Canvas, invalidate, useThree, type ThreeEvent } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "next-themes";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { Crosshair, RotateCcw, X } from "lucide-react";
import type { InventoryItem } from "@/lib/queries";
import { token } from "./chart-theme";
import { Button } from "./ui";
import { int, num } from "@/lib/format";

const MAX_COVER = 60;
const MAX_H = 4.2;

function healthColor(h: string) {
  return h === "shortage_risk" ? token("--danger") : h === "excess" ? token("--risk") : h === "healthy" ? token("--accent") : token("--muted");
}

function Rack({ item, selected, hover, onSelect, onHover, colors }: { item: InventoryItem; selected: boolean; hover: boolean;
  onSelect: (s: string) => void; onHover: (s: string | null) => void; colors: Record<string, string> }) {
  const cover = item.days_of_cover == null ? 0 : Math.min(item.days_of_cover, MAX_COVER);
  const h = Math.max(0.12, (cover / MAX_COVER) * MAX_H);
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
        onPointerOver={(e) => { e.stopPropagation(); onHover(item.sku_id); document.body.style.cursor = "pointer"; invalidate(); }}
        onPointerOut={() => { onHover(null); document.body.style.cursor = ""; invalidate(); }}>
        <boxGeometry args={[1.4, h, 0.85]} />
        <meshStandardMaterial color={color} emissive={selected || hover ? color : "#000000"} emissiveIntensity={selected ? 0.45 : hover ? 0.2 : 0}
          roughness={0.55} metalness={0.05} />
      </mesh>
    </group>
  );
}

/** Requests a frame whenever the canvas size, theme colours or data change (demand rendering). */
function Invalidator({ deps }: { deps: unknown[] }) {
  const size = useThree((s) => s.size);
  const inv = useThree((s) => s.invalidate);
  useEffect(() => {
    inv();
    const t = setTimeout(() => inv(), 120);
    return () => clearTimeout(t);
  }, [size.width, size.height, inv, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

export default function Warehouse3D({ items, selected, onSelect, height = 460, onFail }: {
  items: InventoryItem[]; selected: string | null; onSelect: (sku: string | null) => void; height?: number; onFail?: () => void;
}) {
  const { resolvedTheme } = useTheme();
  const controls = useRef<OrbitControlsImpl | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
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
        onPointerMissed={() => onSelect(null)} role="img" aria-label="3D schematic warehouse. The table and floor plan show the same records."
        // Demand rendering can miss the first frame after a theme remount; request one explicitly.
        onCreated={(s) => {
          requestAnimationFrame(() => s.invalidate()); setTimeout(() => s.invalidate(), 150);
          // A lost context (GPU reset, tab discarded) cannot be recovered mid-session: hand over to the 2D floor plan.
          s.gl.domElement.addEventListener("webglcontextlost", (e) => { e.preventDefault(); onFail?.(); });
        }}>
        <Invalidator deps={[colors, items, selected]} />
        <color attach="background" args={[colors.floor]} />
        <ambientLight intensity={0.7} />
        <directionalLight position={[20, 30, 10]} intensity={1.1} castShadow />
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[center[0], -0.01, center[2]]} receiveShadow>
          <planeGeometry args={[80, 60]} />
          <meshStandardMaterial color={colors.floor} />
        </mesh>
        <gridHelper args={[80, 40, colors.grid, colors.grid]} position={[center[0], 0, center[2]]} />
        {placed.map((it) => (
          <Rack key={`${it.sku_id}@${it.location_id}`} item={it} selected={it.sku_id === selected} hover={it.sku_id === hovered} onSelect={onSelect}
            onHover={setHovered} colors={colors} />
        ))}
        <OrbitControls ref={controls as never} target={center} makeDefault enableDamping={false} maxPolarAngle={Math.PI / 2.15}
          minDistance={6} maxDistance={80} onChange={() => invalidate()} />
      </Canvas>
      <div className="absolute left-3 top-3 flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={reset}><RotateCcw className="size-3.5" aria-hidden /> Reset camera</Button>
        <Button size="sm" variant="outline" onClick={focus} disabled={!selected}><Crosshair className="size-3.5" aria-hidden /> Focus selected</Button>
        <Button size="sm" variant="outline" onClick={() => onSelect(null)} disabled={!selected}><X className="size-3.5" aria-hidden /> Clear selection</Button>
      </div>
      {(() => {
        // Plain DOM overlay (outside the WebGL tree) for the hovered or selected rack.
        const it = placed.find((i) => i.sku_id === (hovered ?? selected));
        return it ? (
          <div className="pointer-events-none absolute bottom-3 right-3 max-w-[260px] rounded-lg border border-line bg-surface/95 px-3 py-2 text-xs shadow-lg" aria-live="polite">
            <div className="num font-semibold">{it.sku_id} · slot {it.slot_id}</div>
            <div className="truncate text-muted">{it.description}</div>
            <div className="num mt-0.5">{int(it.available)} {it.unit} available · {it.days_of_cover == null ? "no sales data" : `${num(it.days_of_cover)} d cover`}</div>
          </div>
        ) : null;
      })()}
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
