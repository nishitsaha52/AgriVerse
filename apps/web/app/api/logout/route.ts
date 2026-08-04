import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export async function POST() {
  const store = await cookies();
  const refreshToken = store.get("agriverse_refresh")?.value;
  if (refreshToken) {
    const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000/api/v1";
    await fetch(`${apiUrl}/auth/logout`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    }).catch(() => undefined);
  }
  const response = NextResponse.json({ status: "signed_out" });
  for (const name of [
    "agriverse_access",
    "agriverse_refresh",
    "agriverse_org",
    "agriverse_role",
  ]) {
    response.cookies.set(name, "", { path: "/", maxAge: 0 });
  }
  return response;
}
