import { NextRequest, NextResponse } from "next/server";

const PUBLIC_API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ provider: string }> },
) {
  const { provider } = await context.params;
  if (!["google", "microsoft"].includes(provider)) {
    return NextResponse.json({ detail: "Unknown OAuth provider" }, { status: 404 });
  }
  const organizationId = request.nextUrl.searchParams.get("organization_id");
  if (!organizationId) {
    return NextResponse.redirect(new URL("/login?error=organization", request.url));
  }
  const target = new URL(`${PUBLIC_API_URL}/auth/staff/oauth/${provider}/start`);
  target.searchParams.set("organization_id", organizationId);
  const inviteCode = request.nextUrl.searchParams.get("invite_code");
  if (inviteCode) target.searchParams.set("invite_code", inviteCode);
  return NextResponse.redirect(target);
}
