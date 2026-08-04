import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000/api/v1";

function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  };
}

export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get("code");
  if (!code) {
    return NextResponse.redirect(new URL("/login?error=oauth", request.url));
  }
  const result = await fetch(`${API_URL}/auth/staff/oauth/exchange`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ code }),
    cache: "no-store",
  });
  if (!result.ok) {
    return NextResponse.redirect(new URL("/login?error=oauth", request.url));
  }
  const tokens = (await result.json()) as {
    access_token: string;
    refresh_token: string;
    expires_in: number;
    organization_id: string;
    role: string;
  };
  const destination =
    tokens.role === "agronomist" || tokens.role === "org_admin"
      ? "/staff/reviews"
      : "/dashboard";
  const response = NextResponse.redirect(new URL(destination, request.url));
  response.cookies.set(
    "agriverse_access",
    tokens.access_token,
    cookieOptions(tokens.expires_in),
  );
  response.cookies.set(
    "agriverse_refresh",
    tokens.refresh_token,
    cookieOptions(7 * 24 * 60 * 60),
  );
  response.cookies.set("agriverse_org", tokens.organization_id, {
    ...cookieOptions(7 * 24 * 60 * 60),
    httpOnly: false,
  });
  response.cookies.set("agriverse_role", tokens.role, {
    ...cookieOptions(7 * 24 * 60 * 60),
    httpOnly: false,
  });
  return response;
}
