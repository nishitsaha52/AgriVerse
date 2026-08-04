"use client";

import { LoaderCircle, Sprout } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { Session } from "@/lib/types";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [organizationId, setOrganizationId] = useState("");
  const [staffInviteCode, setStaffInviteCode] = useState("");
  const staffParams = new URLSearchParams({ organization_id: organizationId });
  if (staffInviteCode) staffParams.set("invite_code", staffInviteCode);
  const staffQuery = staffParams.toString();

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const organizationFromInvite = query.get("organization_id");
    if (organizationFromInvite) setOrganizationId(organizationFromInvite);
    setStaffInviteCode(query.get("invite_code") ?? "");
    const match = document.cookie.match(/(?:^|; )agriverse_org=([^;]*)/);
    if (match && !organizationFromInvite) {
      setOrganizationId(decodeURIComponent(match[1]));
    }
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    const data = new FormData(event.currentTarget);
    try {
      if (mode === "login") {
        await api<Session>("auth/farmer/login", {
          method: "POST",
          body: JSON.stringify({
            phone: data.get("phone"),
            pin: data.get("pin"),
            organization_id: data.get("organization_id"),
          }),
        });
      } else {
        await api<Session>("auth/farmer/register", {
          method: "POST",
          body: JSON.stringify({
            phone: data.get("phone"),
            pin: data.get("pin"),
            invite_code: data.get("invite_code"),
            preferred_language: data.get("preferred_language"),
          }),
        });
      }
      router.push("/dashboard");
      router.refresh();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Unable to continue");
    } finally {
      setPending(false);
    }
  }

  const login = mode === "login";
  return (
    <div className="auth-layout">
      <aside className="auth-aside">
        <Link className="brand" href="/" style={{ color: "white" }}>
          <span className="brand-mark" style={{ background: "white", color: "#103d2a" }}>
            <Sprout size={20} />
          </span>
          AgriVerse
        </Link>
        <blockquote>
          “Every useful answer begins with the field—not with a generic model.”
        </blockquote>
        <small style={{ color: "rgb(255 255 255 / 55%)" }}>
          Deterministic agronomy · Cited advice · Human review
        </small>
      </aside>
      <main className="auth-main">
        <div className="auth-card">
          <div className="eyebrow">{login ? "Welcome back" : "Organization invite"}</div>
          <h1>{login ? "Sign in to your fields" : "Create your farmer account"}</h1>
          <p className="muted">
            {login
              ? "Use the phone number and PIN registered with your field agent."
              : "Your field agent or organization administrator provides the invite."}
          </p>
          <form className="form" onSubmit={submit}>
            <div className="field-group">
              <label htmlFor="phone">Phone number</label>
              <input
                className="input"
                id="phone"
                name="phone"
                inputMode="tel"
                autoComplete="tel"
                placeholder="+91 98765 43210"
                required
              />
            </div>
            <div className="field-group">
              <label htmlFor="pin">PIN</label>
              <input
                className="input"
                id="pin"
                name="pin"
                type="password"
                inputMode="numeric"
                autoComplete={login ? "current-password" : "new-password"}
                pattern="\d{6,12}"
                minLength={6}
                maxLength={12}
                required
              />
            </div>
            {login ? (
              <div className="field-group">
                <label htmlFor="organization_id">Organization ID</label>
                <input
                  className="input"
                  id="organization_id"
                  name="organization_id"
                  value={organizationId}
                  onChange={(event) => setOrganizationId(event.target.value)}
                  placeholder="Provided during enrollment"
                  required
                />
              </div>
            ) : (
              <>
                <div className="field-group">
                  <label htmlFor="invite_code">Invite code</label>
                  <input
                    className="input"
                    id="invite_code"
                    name="invite_code"
                    autoComplete="one-time-code"
                    required
                  />
                </div>
                <div className="field-group">
                  <label htmlFor="preferred_language">Advice language</label>
                  <select
                    className="input"
                    id="preferred_language"
                    name="preferred_language"
                    defaultValue="en"
                  >
                    <option value="en">English</option>
                    <option value="hi">हिन्दी</option>
                    <option value="bn">বাংলা</option>
                    <option value="mr">मराठी</option>
                    <option value="te">తెలుగు</option>
                    <option value="ta">தமிழ்</option>
                    <option value="kn">ಕನ್ನಡ</option>
                  </select>
                </div>
              </>
            )}
            {error ? (
              <div className="error" role="alert">
                {error}
              </div>
            ) : null}
            <button className="button" disabled={pending} type="submit">
              {pending ? <LoaderCircle className="spin" size={17} /> : null}
              {login ? "Sign in" : "Create account"}
            </button>
          </form>
          {login ? (
            <div style={{ marginTop: 24 }}>
              <div className="muted" style={{ marginBottom: 10 }}>
                Staff sign-in
              </div>
              <div style={{ display: "grid", gap: 10 }}>
                <a
                  aria-disabled={!organizationId}
                  className="button button-secondary"
                  href={
                    organizationId
                      ? `/api/oauth/start/google?${staffQuery}`
                      : "#organization_id"
                  }
                >
                  Continue with Google
                </a>
                <a
                  aria-disabled={!organizationId}
                  className="button button-secondary"
                  href={
                    organizationId
                      ? `/api/oauth/start/microsoft?${staffQuery}`
                      : "#organization_id"
                  }
                >
                  Continue with Microsoft
                </a>
              </div>
            </div>
          ) : null}
          <p className="muted" style={{ marginTop: 22 }}>
            {login ? "Have an invite?" : "Already registered?"}{" "}
            <Link
              href={login ? "/register" : "/login"}
              style={{ color: "#1e6647", fontWeight: 750 }}
            >
              {login ? "Create an account" : "Sign in"}
            </Link>
          </p>
        </div>
      </main>
    </div>
  );
}
