import { defineConfig, devices } from "@playwright/test";

// Expects the API (8000), worker and web (3100) to be running: see README "Run locally".
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 60_000,
  retries: 0,
  reporter: [["list"], ["json", { outputFile: "../../artifacts/reports/e2e-results.json" }]],
  use: {
    baseURL: process.env.SUPPLYLENS_WEB_URL ?? "http://localhost:3100",
    trace: "retain-on-failure",
    // Use an already-installed Chromium instead of the version this Playwright release downloads (offline CI, sandboxes).
    ...(process.env.PLAYWRIGHT_CHROMIUM_PATH ? { launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH, args: ["--no-sandbox"] } } : {}),
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } }, testIgnore: /visual\.spec/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /(layout|vitals|a11y|ui-quality)\.spec/ },
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
