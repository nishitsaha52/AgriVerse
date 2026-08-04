import { expect, test } from "@playwright/test";

test("farmer can reach the invite and sign-in journeys", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /Know your field/i }),
  ).toBeVisible();
  await page.getByRole("link", { name: /Start your field record/i }).click();
  await expect(page.getByRole("heading", { name: /Create your farmer account/i })).toBeVisible();
  await page.getByRole("link", { name: /Sign in/i }).click();
  await expect(page.getByRole("heading", { name: /Sign in to your fields/i })).toBeVisible();
});
