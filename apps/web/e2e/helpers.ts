import type { Page } from "@playwright/test";

export async function signIn(page: Page, role: "viewer" | "planner" | "approver" | "tenant_admin") {
  await page.request.post("/api/v1/auth/dev-login", {
    headers: { "X-Requested-With": "supplylens" }, data: { email: `${role}@dev.supplylens.local` },
  });
}
