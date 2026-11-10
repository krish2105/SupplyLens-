import { expect, test } from "./fixtures";
import { signIn } from "./helpers";

// Phase 8 WP6, journey J13: the read-only order and stock status assistant. A viewer opens it from the header, sees the
// first-use state, asks about a product of the synthetic e2e fixture (SYN001) and gets an answer whose sentences link to
// records, is refused a change request, and asks for a person: on a local stack HubSpot is off, so the hand-off is a dry
// run. Esc closes the drawer and focus returns to the header button. Nothing here changes a business record.

const LABEL = "Ask about an order or stock";
// An answer takes about 20 ms on an idle stack; with four browser projects in parallel the API queues it for seconds (QA-P8-04).
const SERVER = { timeout: 15_000 };

test("J13 a viewer asks the status assistant about stock, is refused a change, and hands off to a person (dry run)", async ({ page }) => {
  await signIn(page, "viewer");
  await page.goto("/?ws=uci-research");
  const open = page.getByRole("button", { name: LABEL });
  await open.click();
  const drawer = page.getByRole("dialog", { name: LABEL });
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText("Answers come only from this workspace's records; nothing is generated and nothing is changed.");
  await expect(drawer.locator('[data-state="first_run"] [data-illustration]')).toHaveAttribute("data-illustration", "assistant-ready");
  await expect(drawer.getByLabel("Your question")).toBeFocused();

  await drawer.getByLabel("Your question").fill("stock of SYN001");
  await drawer.getByRole("button", { name: "Ask", exact: true }).click();
  const answer = drawer.getByTestId("assistant-answer");
  await expect(answer).toBeVisible(SERVER);
  await expect(drawer.locator("[data-illustration]")).toHaveCount(0);           // the art is for first use only
  const links = answer.getByRole("link");
  expect(await links.count()).toBeGreaterThan(0);
  await expect(links.first()).toHaveAttribute("href", /ws=uci-research/);

  await drawer.getByLabel("Your question").fill("cancel the order for SYN001");
  await drawer.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(drawer.getByTestId("assistant-withheld")).toContainText("only reads records", SERVER);

  await drawer.getByRole("button", { name: "Talk to a person" }).click();
  await expect(drawer.getByTestId("assistant-handoff")).toHaveText("Dry run: ticket not sent — HubSpot is not connected.", SERVER);

  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(open).toBeFocused();
});

test("J13 the command palette opens the assistant, and the drawer fits a phone screen", async ({ page }) => {
  await signIn(page, "viewer");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/inventory?ws=uci-research");
  await page.getByRole("button", { name: "Open command palette" }).click();
  await page.getByRole("combobox", { name: "Search pages, products and commands" }).fill("ask about");
  await page.keyboard.press("Enter");
  const drawer = page.getByRole("dialog", { name: LABEL });
  await expect(drawer).toBeVisible();
  const box = await drawer.boundingBox();
  expect(box!.width).toBeLessThanOrEqual(390);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await drawer.getByLabel("Your question").fill("RETRO");                       // several fixture products may match
  await drawer.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(drawer.getByTestId("assistant-answer").or(drawer.getByTestId("assistant-choose")).or(drawer.getByTestId("assistant-withheld"))).toBeVisible(SERVER);
});
