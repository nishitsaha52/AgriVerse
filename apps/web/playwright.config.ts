import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:3101",
    trace: "on-first-retry",
  },
  webServer: {
    command: "corepack pnpm dev --port 3101",
    env: {
      APP_ENV: "production",
      STAFF_PIN_LOGIN_ENABLED: "true",
      KEYCLOAK_ISSUER_URL: "http://127.0.0.1:8080/realms/test",
      KEYCLOAK_CLIENT_ID: "agriverse-e2e",
      GOOGLE_CLIENT_ID: "",
      MICROSOFT_CLIENT_ID: "",
      NEXT_PUBLIC_API_URL: "http://127.0.0.1:8000/api/v1",
    },
    url: "http://127.0.0.1:3101",
    reuseExistingServer: false,
    timeout: 120_000,
  },
  projects: [
    {
      name: "chromium-mobile",
      use: { ...devices["Pixel 7"] },
    },
  ],
});
