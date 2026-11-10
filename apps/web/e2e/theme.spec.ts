// Phase 8 WP0: defects the owner saw on the hosted demo on 2026-11-10 (docs/screenshots/phase8/), each pinned by the
// behaviour that was wrong. F1: the 3D warehouse kept the dark theme's floor in light theme. F2: capabilities built on
// simulated data showed the observed-green "available". F3: the 3D legend was translucent over the racks.
// Runs on the desktop project (Chromium) and, for the 3D theme checks, on WebKit.
import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";
import { getJson, signIn } from "./helpers";

type Theme = "light" | "dark";
type RGB = [number, number, number];
// --bg-deep in app/globals.css: the 3D view clears to it and lays its floor in it
const BG_DEEP: Record<Theme, RGB> = { light: [0xe9, 0xf0, 0xed], dark: [0x09, 0x10, 0x12] };
const other = (t: Theme): Theme => (t === "light" ? "dark" : "light");
const dist = (a: RGB, b: RGB) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

const canvas = (page: Page) => page.locator('[aria-label^="3D schematic warehouse"] canvas');

/** Median colour of a patch of the rendered 3D view: a floor area above the racks, away from the toolbar and legend. */
async function floorColour(page: Page): Promise<RGB> {
  await expect(canvas(page)).toBeVisible();
  // demand rendering: the view draws after the theme's next frame; give it a few frames to settle
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 300)))));
  const png = (await canvas(page).screenshot()).toString("base64");
  return page.evaluate(async (b64: string): Promise<RGB> => {
    const img = new Image();
    img.src = `data:image/png;base64,${b64}`;
    await img.decode();
    const c = document.createElement("canvas");
    c.width = img.width; c.height = img.height;
    const g = c.getContext("2d")!;
    g.drawImage(img, 0, 0);
    // top-right corner region: floor and background only (racks sit in the middle, toolbar top-left, legend bottom-left)
    const x0 = Math.round(img.width * 0.88), y0 = Math.round(img.height * 0.2), n = 15;
    const d = g.getImageData(x0, y0, n, n).data;
    const median = (k: number) => { const v: number[] = []; for (let i = k; i < d.length; i += 4) v.push(d[i] ?? 0); v.sort((a, b) => a - b); return v[v.length >> 1] ?? 0; };
    return [median(0), median(1), median(2)];
  }, png);
}

async function expectFloorIn(page: Page, theme: Theme) {
  await expect(page.locator("html")).toHaveClass(new RegExp(`\\b${theme}\\b`));
  await expect.poll(async () => {
    const c = await floorColour(page);
    return dist(c, BG_DEEP[theme]) < dist(c, BG_DEEP[other(theme)]) ? "this theme" : `the ${other(theme)} theme (rgb ${c.join(",")})`;
  }, { message: `3D floor should use the ${theme} theme's --bg-deep`, timeout: 10_000 }).toBe("this theme");
}

async function pickTheme(page: Page, theme: Theme) {
  await page.getByRole("radio", { name: theme === "light" ? "Light theme" : "Dark theme" }).check({ force: true });
}

for (const path of ["/", "/inventory"] as const) {
  test.describe(`F1: 3D warehouse follows the theme on ${path === "/" ? "Overview" : "Inventory"}`, () => {
    test.use({ viewport: { width: 1440, height: 900 } });

    test("system dark, app set to light: the floor is light", async ({ page }) => {
      await page.emulateMedia({ colorScheme: "dark" });
      await page.addInitScript(() => { try { localStorage.setItem("supplylens-theme", "light"); } catch { /* none */ } });
      await signIn(page, "viewer");
      await page.goto(`${path}?ws=uci-research`);
      await expectFloorIn(page, "light");
    });

    test("switching dark → light → dark at runtime repaints the floor each time", async ({ page }) => {
      await page.emulateMedia({ colorScheme: "light" });
      await page.addInitScript(() => { try { localStorage.setItem("supplylens-theme", "dark"); } catch { /* none */ } });
      await signIn(page, "viewer");
      await page.goto(`${path}?ws=uci-research`);
      await expectFloorIn(page, "dark");
      await pickTheme(page, "light");
      await expectFloorIn(page, "light");
      await pickTheme(page, "dark");
      await expectFloorIn(page, "dark");
    });
  });
}

test("F2: capabilities built on simulated, synthetic or assumed data name that basis beside their status", async ({ page }) => {
  test.skip((page.viewportSize()?.width ?? 1440) < 768, "same markup at every width; checked once on desktop");
  await signIn(page, "viewer");
  const o = await getJson<{ capabilities: { capability: string; status: string; basis: string | null }[] }>(page, "/api/v1/overview");
  const flagged = o.capabilities.filter((c) => c.basis && c.basis !== "observed");
  expect(flagged.length, "the matrix has simulated or assumed rows to check").toBeGreaterThan(0);
  await page.goto("/?ws=uci-research");
  const card = page.locator("section, div").filter({ has: page.getByText("What this data can answer", { exact: true }) }).last();
  for (const c of flagged) {
    const row = card.getByRole("listitem").filter({ hasText: c.capability });
    await expect(row, `${c.capability}: basis "${c.basis}" must be shown`).toContainText(new RegExp(`\\b${c.basis}\\b`, "i"));
    // never the observed-green style (Status tone "ok") for a value that is not observed
    await expect(row.locator("[data-basis]"), `${c.capability} carries its basis`).toHaveAttribute("data-basis", c.basis!);
    await expect(row.locator("[data-tone=ok]")).toHaveCount(0);
  }
});

test("F3: the 3D legend and hover card are opaque", async ({ page }) => {
  test.skip((page.viewportSize()?.width ?? 1440) < 768, "the 3D view is desktop and tablet only");
  await signIn(page, "viewer");
  await page.goto("/?ws=uci-research");
  await expect(canvas(page)).toBeVisible();
  // computed colours come back as rgba(r, g, b, a) or, for Tailwind 4 colour-mix utilities, oklab(l a b / alpha)
  const alphaOf = (el: Element) => {
    const bg = getComputedStyle(el).backgroundColor;
    const slash = bg.match(/\/\s*([\d.]+)\s*\)$/);
    if (slash) return Number(slash[1]);
    const rgba = bg.match(/^rgba\(([^)]+)\)$/);
    return rgba ? Number(rgba[1]?.split(",")[3] ?? 1) : 1;
  };
  const legend = page.getByText("Schematic", { exact: true }).locator("..");
  expect(await legend.evaluate(alphaOf), "legend background alpha").toBe(1);
  // disabled toolbar buttons over the view stay opaque and readable in both themes (WCAG AA text contrast, 4.5:1)
  for (const theme of ["light", "dark"] as const) {
    await pickTheme(page, theme);
    await expect(page.locator("html")).toHaveClass(new RegExp(`\\b${theme}\\b`));
    for (const name of ["Focus selected", "Clear selection"]) {
      const btn = page.getByRole("button", { name });
      await expect(btn).toBeDisabled();
      const { opacity, ratio } = await btn.evaluate((el) => {
        const lum = (css: string) => {
          const c = document.createElement("canvas").getContext("2d")!;
          c.fillStyle = css; c.fillRect(0, 0, 1, 1);
          const [r = 0, g = 0, b = 0] = Array.from(c.getImageData(0, 0, 1, 1).data.slice(0, 3))
            .map((x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
          return 0.2126 * r + 0.7152 * g + 0.0722 * b;
        };
        const st = getComputedStyle(el);
        const a = lum(st.color), b = lum(st.backgroundColor);
        return { opacity: Number(st.opacity), ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) };
      });
      expect(opacity, `${name} (${theme}) opacity`).toBe(1);
      expect(ratio, `${name} (${theme}) text contrast`).toBeGreaterThanOrEqual(4.5);
    }
  }
  // the hover card appears for a selected rack: select one from the table-free path (the first rack in the view)
  await page.goto("/inventory?ws=uci-research");
  await expect(canvas(page)).toBeVisible();
  const firstRow = page.getByRole("row").nth(1);
  await firstRow.click();
  const card = page.locator('[aria-live="polite"]').filter({ hasText: /slot/ }).first();
  await expect(card).toBeVisible();
  expect(await card.evaluate(alphaOf), "hover card background alpha").toBe(1);
});
