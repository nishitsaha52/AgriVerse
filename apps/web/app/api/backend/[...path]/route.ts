import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000/api/v1";
const AUTH_PATHS = new Set([
  "auth/farmer/login",
  "auth/farmer/register",
  "auth/staff/pin-login",
  "auth/refresh",
]);

function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  };
}

async function forward(
  request: NextRequest,
  path: string,
  accessToken: string | undefined,
): Promise<Response> {
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const idempotency = request.headers.get("idempotency-key");
  if (idempotency) headers.set("idempotency-key", idempotency);
  if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);
  const body =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.clone().arrayBuffer();
  return fetch(`${API_URL}/${path}${request.nextUrl.search}`, {
    method: request.method,
    headers,
    body,
    cache: "no-store",
  });
}

async function handler(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path: parts } = await context.params;
  const path = parts.join("/");
  const store = await cookies();
  let accessToken = store.get("agriverse_access")?.value;
  let response = await forward(request, path, accessToken);

  if (response.status === 401 && accessToken && !AUTH_PATHS.has(path)) {
    const refreshToken = store.get("agriverse_refresh")?.value;
    if (refreshToken) {
      const refreshed = await fetch(`${API_URL}/auth/refresh`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
        cache: "no-store",
      });
      if (refreshed.ok) {
        const tokens = (await refreshed.json()) as {
          access_token: string;
          refresh_token: string;
          expires_in: number;
        };
        accessToken = tokens.access_token;
        store.set("agriverse_access", tokens.access_token, cookieOptions(tokens.expires_in));
        store.set(
          "agriverse_refresh",
          tokens.refresh_token,
          cookieOptions(60 * 24 * 60 * 60),
        );
        response = await forward(request, path, accessToken);
      }
    }
  }

  const text = await response.text();
  const output = new NextResponse(text || null, {
    status: response.status,
    headers: {
      "content-type": response.headers.get("content-type") ?? "application/json",
      "x-request-id": response.headers.get("x-request-id") ?? "",
    },
  });
  if (response.ok && AUTH_PATHS.has(path) && text) {
    const tokens = JSON.parse(text) as {
      access_token?: string;
      refresh_token?: string;
      expires_in?: number;
      organization_id?: string;
      role?: string;
    };
    if (tokens.access_token && tokens.refresh_token) {
      const authOutput = NextResponse.json(
        {
          organization_id: tokens.organization_id,
          role: tokens.role,
          expires_in: tokens.expires_in,
        },
        { status: response.status },
      );
      authOutput.cookies.set(
        "agriverse_access",
        tokens.access_token,
        cookieOptions(tokens.expires_in ?? 900),
      );
      authOutput.cookies.set(
        "agriverse_refresh",
        tokens.refresh_token,
        cookieOptions(60 * 24 * 60 * 60),
      );
      authOutput.cookies.set("agriverse_org", tokens.organization_id ?? "", {
        ...cookieOptions(60 * 24 * 60 * 60),
        httpOnly: false,
      });
      authOutput.cookies.set("agriverse_role", tokens.role ?? "", {
        ...cookieOptions(60 * 24 * 60 * 60),
        httpOnly: false,
      });
      return authOutput;
    }
  }
  return output;
}

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
