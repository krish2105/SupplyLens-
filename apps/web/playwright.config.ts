import { defineConfig, devices } from "@playwright/test";

// Expects the API (8000), worker and web (3100) to be running: see README "Run locally".
export default defineConfig({
  testDir: "./e2e",
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
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /(layout|vitals|a11y)\.spec/ },
  ],
});
