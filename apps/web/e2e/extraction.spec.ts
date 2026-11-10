import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";
import { getJson, signIn } from "./helpers";

// Phase 8 WP7, journey J14 (read-only part): a document's draft terms, found by rules, in the Policies reader. Uploading a
// PDF and confirming a field (the rest of J14 in the brief) are not built: uploads stay plain text (D-076) and confirming
// needs a terms record of its own. The Reference Supplier A agreement v1 (Demo workspace, fictional) states a minimum order
// quantity, lead time, unit price, effective date and supplier, so the rules find fields there.

type Field = { field: string; value: string; start: number; end: number; source: string };
type Doc = { version_id: string; version_label: string; title: string };
const NOTE = "Draft: not used for planning. A person must confirm a field before it is used; confirming arrives in a later step.";

async function reference(page: Page) {
  const docs = await getJson<Doc[]>(page, "/api/v1/documents", "demo");
  const doc = docs.find((d) => d.title === "Reference Supplier A agreement" && d.version_label === "v1") ?? docs[0]!;
  const text = (await getJson<{ text: string }>(page, `/api/v1/documents/versions/${doc.version_id}`, "demo")).text;
  const terms = await getJson<{ status: string; fields: Field[] }>(page, `/api/v1/documents/versions/${doc.version_id}/extracted-terms`, "demo");
  return { doc, text, terms };
}

async function openReader(page: Page, doc: Doc) {
  await page.goto("/policies?ws=demo");
  const entry = page.locator("li").filter({ hasText: doc.title }).first();
  await entry.getByRole("button", { name: doc.version_label, exact: true }).click();
  return page.getByRole("region", { name: "Document reader" });
}

test("J14 a viewer opens a document's extracted terms: DRAFT, fields with their source, and Show in text marks the span", async ({ page }) => {
  await signIn(page, "viewer");
  const { doc, text, terms } = await reference(page);
  expect(terms.status).toBe("draft");
  const reader = await openReader(page, doc);
  await expect(reader.getByRole("tab", { name: "Document text" })).toHaveAttribute("aria-selected", "true");
  await reader.getByRole("tab", { name: "Extracted terms" }).click();
  await expect(reader.getByRole("tab", { name: "Extracted terms" })).toHaveAttribute("aria-selected", "true");
  const panel = reader.getByTestId("extracted-terms");
  await expect(panel.getByText("DRAFT", { exact: true })).toBeVisible();
  await expect(panel).toContainText(NOTE);
  if (terms.fields.length === 0) {                 // extraction ran and found nothing: the empty state, with its art
    await expect(panel.getByText("No terms found in this version")).toBeVisible();
    await expect(panel.locator('[data-state="empty_scope"] [data-illustration]')).toHaveAttribute("data-illustration", "empty-extraction");
    return;
  }
  await expect(panel.getByRole("row")).toHaveCount(terms.fields.length + 1);           // one row per field, plus the header
  await expect(panel.getByRole("cell", { name: "rule", exact: true })).toHaveCount(terms.fields.length);
  const pick = terms.fields.find((f) => f.field === "moq") ?? terms.fields[0]!;
  // by its span, not its text: a longer field (minimum commitment) can contain the same words
  await panel.getByRole("button", { name: new RegExp(`^Show in text.*characters ${pick.start} to ${pick.end}$`) }).click();
  await expect(reader.getByRole("tab", { name: "Document text" })).toHaveAttribute("aria-selected", "true");
  const mark = reader.locator('pre mark[data-highlight="extracted"]');
  await expect(mark).toHaveText(text.slice(pick.start, pick.end));
  await expect(reader.getByLabel("Document text, scrollable")).toBeFocused();         // keyboard users land on the passage
  await expect(mark).toBeInViewport();
  await expect(reader.getByTestId("extracted-highlight")).toContainText(`characters ${pick.start}–${pick.end}`);
  await reader.getByRole("button", { name: "Back to extracted terms" }).click();
  await expect(reader.getByRole("tab", { name: "Extracted terms" })).toBeFocused();
});

test("J14 the reader tabs and Show in text work from the keyboard alone", async ({ page }) => {
  await signIn(page, "viewer");
  const { doc, terms } = await reference(page);
  test.skip(terms.fields.length === 0, "no fields to show in this stack's reference document");
  const reader = await openReader(page, doc);
  await reader.getByRole("tab", { name: "Document text" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(reader.getByRole("tab", { name: "Extracted terms" })).toBeFocused();
  await expect(reader.getByRole("tab", { name: "Extracted terms" })).toHaveAttribute("aria-selected", "true");
  const show = reader.getByRole("button", { name: /^Show in text/ }).first();
  await expect(show).toBeVisible();
  for (let i = 0; i < 6 && !(await show.evaluate((b) => b === document.activeElement)); i++) await page.keyboard.press("Tab");
  await expect(show).toBeFocused();                     // reachable with Tab (past the table's scroll region)
  await page.keyboard.press("Enter");
  await expect(reader.locator('pre mark[data-highlight="extracted"]')).toBeVisible();
  await expect(reader.getByLabel("Document text, scrollable")).toBeFocused();
});

test("J14 at phone width the terms table scrolls inside its card, never the page", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, "viewer");
  const { doc, terms } = await reference(page);
  const reader = await openReader(page, doc);
  await reader.getByRole("tab", { name: "Extracted terms" }).click();
  await expect(reader.getByTestId("extracted-terms").getByText("DRAFT", { exact: true })).toBeVisible();
  if (terms.fields.length) await expect(reader.getByRole("region", { name: "Extracted terms, scrollable" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});

test("J14 no terms found shows the extraction empty state; a failed request shows an error with retry", async ({ page }) => {
  await signIn(page, "viewer");
  const { doc } = await reference(page);
  const path = `**/api/v1/documents/versions/${doc.version_id}/extracted-terms`;
  await page.route(path, (route) => route.fulfill({ json: { status: "draft", version_id: doc.version_id, extractor: "rules-v1", fields: [], note: "" } }));
  let reader = await openReader(page, doc);
  await reader.getByRole("tab", { name: "Extracted terms" }).click();
  const empty = reader.locator('[data-state="empty_scope"]');
  await expect(empty).toContainText("No terms found in this version");
  await expect(empty.locator("[data-illustration]")).toHaveAttribute("data-illustration", "empty-extraction");
  await expect(reader.getByTestId("extracted-terms").getByText("DRAFT", { exact: true })).toBeVisible();
  await page.unroute(path);
  await page.route(path, (route) => route.fulfill({ status: 500, json: { code: "server_error", message: "The server hit an unexpected error." } }));
  reader = await openReader(page, doc);
  await reader.getByRole("tab", { name: "Extracted terms" }).click();
  await expect(reader.getByRole("alert")).toContainText("The server hit an unexpected error.", { timeout: 15_000 });   // after two retries
  await expect(reader.getByRole("button", { name: "Try again" })).toBeVisible();
  await expect(reader.locator("[data-illustration]")).toHaveCount(0);           // errors never use art
});
