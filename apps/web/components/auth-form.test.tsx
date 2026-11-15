import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthForm } from "./auth-form";
import LoginPage from "../app/login/page";

const mocks = vi.hoisted(() => ({ api: vi.fn(), push: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  api: mocks.api,
}));

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/login");
});
afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

function submitLogin() {
  fireEvent.change(screen.getByLabelText("Phone number"), { target: { value: "+919876543210" } });
  fireEvent.change(screen.getByLabelText("PIN"), { target: { value: "012345" } });
  fireEvent.change(screen.getByLabelText("Organization ID"), { target: { value: "example-org" } });
  fireEvent.submit(screen.getByRole("button", { name: "Sign in" }).closest("form")!);
}

describe("login account selection", () => {
  it("supports production staff PIN login without any OIDC provider", async () => {
    vi.stubEnv("APP_ENV", "production");
    vi.stubEnv("STAFF_PIN_LOGIN_ENABLED", undefined);
    vi.stubEnv("KEYCLOAK_ISSUER_URL", "");
    vi.stubEnv("GOOGLE_CLIENT_ID", "");
    vi.stubEnv("MICROSOFT_CLIENT_ID", "");
    mocks.api.mockResolvedValue({ role: "org_admin" });
    render(<LoginPage />);
    expect(screen.queryByRole("link", { name: /Continue with/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Sign in as staff/admin with PIN" }));
    submitLogin();
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/staff/reviews"));
    expect(mocks.api).toHaveBeenCalledWith("auth/staff/pin-login", expect.anything());
  });

  it.each(["false", "0", "no", "off"])("hides production staff PIN login when disabled with %s", (value) => {
    vi.stubEnv("APP_ENV", "production");
    vi.stubEnv("STAFF_PIN_LOGIN_ENABLED", value);
    render(<LoginPage />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("offers only configured OIDC providers", () => {
    render(<AuthForm mode="login" staffProviders={["keycloak"]} />);
    fireEvent.change(screen.getByLabelText("Organization ID"), {
      target: { value: "example-org" },
    });
    expect(screen.getByRole("link", { name: "Continue with Keycloak" })).toHaveAttribute(
      "href", "/api/oauth/start/keycloak?organization_id=example-org",
    );
    expect(screen.queryByRole("link", { name: "Continue with Google" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Continue with Microsoft" })).not.toBeInTheDocument();
  });

  it("hides OIDC buttons until a provider is configured", () => {
    render(<AuthForm mode="login" />);
    expect(screen.queryByRole("link", { name: /Continue with/i })).not.toBeInTheDocument();
  });

  it("uses the farmer endpoint by default", async () => {
    mocks.api.mockResolvedValue({ role: "farmer" });
    render(<AuthForm mode="login" allowStaffPin />);
    submitLogin();
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/dashboard"));
    expect(mocks.api).toHaveBeenCalledWith("auth/farmer/login", expect.anything());
  });

  it("uses the bootstrap link to sign in as admin", async () => {
    window.history.replaceState({}, "", "/login?organization_id=example-org&staff_pin=1");
    mocks.api.mockResolvedValue({ role: "org_admin" });
    render(<AuthForm mode="login" allowStaffPin />);
    expect(screen.getByRole("checkbox")).toBeChecked();
    submitLogin();
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/staff/reviews"));
    expect(mocks.api).toHaveBeenCalledWith("auth/staff/pin-login", {
      method: "POST",
      body: JSON.stringify({ phone: "+919876543210", pin: "012345", organization_id: "example-org" }),
    });
  });

  it("ignores staff PIN query parameters when staff PIN is unavailable", async () => {
    window.history.replaceState({}, "", "/login?staff_pin=1");
    mocks.api.mockResolvedValue({ role: "farmer" });
    render(<AuthForm mode="login" />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    submitLogin();
    await waitFor(() => expect(mocks.api).toHaveBeenCalledWith("auth/farmer/login", expect.anything()));
  });
});
