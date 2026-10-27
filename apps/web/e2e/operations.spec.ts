// Operations features F1-F4: product classes, the CO2 trade-off, cited answers and the new studies. Runs on the desktop and phone projects against the synthetic CI fixture.
import { expect, test } from "./fixtures";
import { signIn } from "./helpers";

test("inventory classes: ABC/XYZ matrix, safety stock, and a higher service level costs more to hold", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto("/inventory?ws=uci-research");
  const panel = page.getByRole("region", { name: "Product classes and the cost of service" });
  await panel.scrollIntoViewIfNeeded();
  await expect(panel.getByRole("table", { name: "Products by ABC and XYZ class" })).toBeVisible();
  await expect(panel.getByRole("img", { name: /holding cost of safety stock/ })).toBeVisible();
  const cost = async () => Number((await panel.getByText(/a year to hold/).textContent())!.match(/[\d,]+\.\d\d/)![0].replace(/,/g, ""));
  const before = await cost();
  await panel.getByLabel("Class A").selectOption("0.995");
  await expect.poll(cost).toBeGreaterThan(before);
  await expect(panel.getByRole("region", { name: "Safety stock per stocked product, scrollable" })).toBeVisible();
});

test("scenario studio traces the cost, service and CO2 trade-off for the draft", async ({ page }) => {
  await signIn(page, "planner");
  await page.goto("/scenarios?ws=uci-research");
  const card = page.getByRole("region", { name: "Cost, service and CO₂" });
  await card.scrollIntoViewIfNeeded();
  await card.getByRole("button", { name: "Trace the trade-off for the draft" }).click();
  const rows = card.getByRole("table", { name: "Plan under each CO2 cap" }).locator("tbody tr");
  await expect(rows.first()).toContainText("none", { timeout: 30_000 });
  const co2 = await rows.evaluateAll((trs) => trs.map((tr) => Number(tr.children[1]!.textContent)).filter((n) => !Number.isNaN(n)));
  expect(co2.length).toBeGreaterThan(3);
  expect(co2.every((v, i) => i === 0 || v <= co2[i - 1]!)).toBe(true);        // a tighter cap never emits more
  await expect(card.getByText(/unit weight 0.5 kg \(assumed/)).toBeVisible();   // the assumptions are on the screen
});

test("a viewer cannot run the trade-off; the button says why", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto("/scenarios?ws=uci-research");
  await expect(page.getByRole("button", { name: "Trace the trade-off for the draft" })).toBeDisabled();
});

test("policies: the cited-answer panel says when generation is off and keeps the passages as the answer", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto("/policies?ws=demo");
  await page.getByRole("button", { name: "Search evidence" }).click();
  const panel = page.getByTestId("cited-answer");
  await expect(panel).toBeVisible();
  await panel.getByRole("button", { name: "Write a cited answer" }).click();
  // CI and the public demo have no local model: the answer is the cited passages, and the panel says so
  await expect(panel.getByText(/switched off here|Nothing was generated|withheld|Written by/)).toBeVisible({ timeout: 30_000 });
});

test("research shows the operations studies with their reviewed headlines", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto("/research?ws=uci-research");
  const section = page.getByRole("region", { name: /Operations studies/ });
  await section.scrollIntoViewIfNeeded();
  for (const id of ["E1", "FA1"]) await expect(section.getByText(`Study ${id}`)).toBeVisible();
  await expect(section.getByText(/halving CO2 costs 13.8 points of coverage/)).toBeVisible();
  await expect(section.getByRole("img", { name: /exact front and NSGA-II/ })).toBeVisible();
});
