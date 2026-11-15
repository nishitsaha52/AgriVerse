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

test("bootstrap link selects admin PIN login in production", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const organizationId = "b236ce6d-cbf2-4093-91f2-04dac7f6ba81";
  await page.goto(`/login?organization_id=${organizationId}&staff_pin=1`);
  await expect(page.getByLabel("Organization ID")).toHaveValue(organizationId);
  await expect(page.getByRole("checkbox", { name: /staff\/admin with PIN/i })).toBeChecked();
  expect(errors).toEqual([]);
});

test("configured Keycloak sign-in reaches the OIDC start route", async ({ page }) => {
  const organizationId = "b236ce6d-cbf2-4093-91f2-04dac7f6ba81";
  await page.goto(`/login?organization_id=${organizationId}`);
  const link = page.getByRole("link", { name: "Continue with Keycloak" });
  await expect(link).toHaveAttribute(
    "href", `/api/oauth/start/keycloak?organization_id=${organizationId}`,
  );
  await expect(page.getByRole("link", { name: "Continue with Google" })).toHaveCount(0);
  const response = await page.request.get((await link.getAttribute("href"))!, { maxRedirects: 0 });
  expect(response.status()).toBe(307);
  const target = new URL(response.headers().location);
  expect(target.pathname).toBe("/api/v1/auth/staff/oauth/keycloak/start");
  expect(target.searchParams.get("organization_id")).toBe(organizationId);
});
