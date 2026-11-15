import type { Metadata } from "next";

import { AuthForm } from "@/components/auth-form";

export const metadata: Metadata = { title: "Sign in" };
export const dynamic = "force-dynamic";

export default function LoginPage() {
  const allowStaffPin = !["false", "0", "no", "off"].includes(
    (process.env.STAFF_PIN_LOGIN_ENABLED ?? "true").trim().toLowerCase(),
  );
  const staffProviders = [
    ...(process.env.KEYCLOAK_ISSUER_URL && process.env.KEYCLOAK_CLIENT_ID ? ["keycloak"] : []),
    ...(process.env.GOOGLE_CLIENT_ID ? ["google"] : []),
    ...(process.env.MICROSOFT_CLIENT_ID ? ["microsoft"] : []),
  ];
  return (
    <AuthForm
      mode="login"
      allowStaffPin={allowStaffPin}
      staffProviders={staffProviders}
    />
  );
}
