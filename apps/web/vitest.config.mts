// Unit and component tests (P2-FE-03): `npm test`. Browser journeys stay in Playwright (e2e/).
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  test: { environment: "jsdom", include: ["{lib,components,app}/**/*.test.{ts,tsx}"], restoreMocks: true },
});
