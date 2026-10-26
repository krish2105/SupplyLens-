import { defineConfig, devices } from "@playwright/test";

// Expects the API (8000), worker and web (3100) to be running: see README "Run locally".
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 60_000,
  retries: 0,
  // E2E_JSON: a suite run as its own CI step (lab vitals) writes its own results file; acceptance evidence reads both
  reporter: [["list"], ["json", { outputFile: process.env.E2E_JSON ?? "../../artifacts/reports/e2e-results.json" }]],
  use: {
    baseURL: process.env.SUPPLYLENS_WEB_URL ?? "http://localhost:3100",
    trace: "retain-on-failure",
    // Use an already-installed Chromium instead of the version this Playwright release downloads (offline CI, sandboxes).
    ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH, args: ["--no-sandbox"] } } : {}),
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } }, testIgnore: /(visual|vitals)\.spec/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /(layout|a11y|ui-quality)\.spec/ },
    // Lab Web Vitals (UX-011) measure the app, so they run alone and one at a time: run beside other suites they measured
    // the machine's load (QA-4B-01: the INP proxy read 224–232 ms on CI only while other browsers ran; with every core
    // busy, interactions took 0.7–1.7 s with or without WebGL). CI runs them in their own step with --workers 1.
    { name: "vitals-desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } }, testMatch: /vitals\.spec/, workers: 1 },
    { name: "vitals-mobile", use: { ...devices["Pixel 7"] }, testMatch: /vitals\.spec/, workers: 1 },
    // Screenshot regression (Phase 4B): sets its own widths and themes; run alone, on a freshly seeded stack, before the
    // suites above change data (CI does). Per-platform baselines under e2e/visual.spec.ts-snapshots/, reviewed before commit.
    { name: "visual", use: { ...devices["Desktop Chrome"] }, testMatch: /visual\.spec/ },
    // Other engines (Phase 4): the user journeys on Firefox and WebKit, and the purchase journey on an iPhone-sized WebKit.
    // Emulation only: no physical device is involved.
    { name: "firefox", use: { ...devices["Desktop Firefox"], viewport: { width: 1440, height: 900 } }, testMatch: /(journey|workflows)\.spec/ },
    { name: "webkit", use: { ...devices["Desktop Safari"], viewport: { width: 1440, height: 900 } }, testMatch: /(journey|workflows)\.spec/ },
    { name: "mobile-safari", use: { ...devices["iPhone 13"] }, testMatch: /journey\.spec/ },
  ],
});
