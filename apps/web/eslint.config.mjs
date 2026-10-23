// ESLint (P2-FE-03): Next.js core-web-vitals + TypeScript rules, which include the React hooks rules. CI runs it.
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const config = [
  ...nextVitals,
  ...nextTs,
  // Browser tests read untyped JSON from the API through Playwright; explicit any is acceptable there.
  { files: ["e2e/**"], rules: { "@typescript-eslint/no-explicit-any": "off" } },
  { ignores: [".next/**", ".next-build/**", "node_modules/**", "playwright-report/**", "test-results/**", "next-env.d.ts"] },
];

export default config;
