import { expect, test } from "./fixtures";
import { signIn } from "./helpers";

// FE-P8-07 (owner report 2026-11-10): opening the site with a session that had ended showed an empty dashboard for
// seconds before sign-in. A dead session's cookie is now deleted by the API, so the next visit is redirected to sign-in
// before any page renders; and a session check that takes long says why instead of leaving a silent empty screen.

test("a dead session cookie is deleted, and the next visit goes straight to sign-in", async ({ page, context, baseURL }) => {
  const host = new URL(baseURL!).hostname;
  await context.addCookies([{ name: "sl_session", value: "not-a-valid-session", domain: host, path: "/" }]);
  await page.goto("/inventory?ws=uci-research");
  await expect(page).toHaveURL(/\/login\?next=/, { timeout: 15_000 });                       // the API said 401
  expect((await context.cookies()).some((c) => c.name === "sl_session")).toBe(false);     // ...and deleted the cookie
  const r = await page.request.get("/inventory?ws=uci-research", { maxRedirects: 0 });
  expect(r.status()).toBe(307);                                                              // no app shell at all now
  expect(r.headers()["location"]).toContain("/login");
});

test("a slow session check says the service is starting, then the page fills in", async ({ page }) => {
  await signIn(page, "viewer");
  await page.route("**/api/v1/me", async (route) => { await new Promise((r) => setTimeout(r, 3_000)); await route.continue(); });
  await page.goto("/settings?ws=uci-research");
  const notice = page.getByTestId("service-waking");
  await expect(notice).toBeVisible({ timeout: 2_900 });
  await expect(notice).toContainText("Starting SupplyLens.");
  await expect(page.getByText("Appearance, connections and audit")).toBeVisible({ timeout: 15_000 });
  await expect(notice).toBeHidden({ timeout: 15_000 });
});

test("a quick session check shows no notice", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto("/settings?ws=uci-research");
  await expect(page.getByText("Appearance, connections and audit")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("service-waking")).toHaveCount(0);
});

test("the sign-in page says the service is starting when its first answer is slow", async ({ page }) => {
  await page.route("**/api/v1/auth/config", async (route) => { await new Promise((r) => setTimeout(r, 3_000)); await route.continue(); });
  await page.goto("/login");
  await expect(page.getByTestId("service-waking")).toContainText("Starting SupplyLens.", { timeout: 2_900 });
  await expect(page.getByRole("button", { name: /Dev Viewer/ }).first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("service-waking")).toBeHidden();
});
