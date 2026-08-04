"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, LoaderCircle, Stethoscope } from "lucide-react";
import Link from "next/link";
import { FormEvent, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { Review } from "@/lib/types";

export function ReviewClient() {
  const queryClient = useQueryClient();
  const [error, setError] = useState("");
  const reviews = useQuery({
    queryKey: ["reviews"],
    queryFn: () => api<Review[]>("reviews"),
  });
  const decision = useMutation({
    mutationFn: ({
      reviewId,
      diagnosis,
      outcome,
    }: {
      reviewId: string;
      diagnosis: string | null;
      outcome: "confirmed" | "corrected" | "indeterminate";
    }) =>
      api(`reviews/${reviewId}/decision`, {
        method: "POST",
        idempotency: true,
        body: JSON.stringify({
          decision: outcome,
          confirmed_diagnosis: diagnosis,
        }),
      }),
    onSuccess: () => {
      setError("");
      void queryClient.invalidateQueries({ queryKey: ["reviews"] });
    },
    onError: (reason) =>
      setError(reason instanceof ApiError ? reason.message : "Decision failed"),
  });

  function submit(event: FormEvent<HTMLFormElement>, reviewId: string) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const outcome = form.get("decision") as "confirmed" | "corrected" | "indeterminate";
    decision.mutate({
      reviewId,
      outcome,
      diagnosis:
        outcome === "indeterminate" ? null : String(form.get("confirmed_diagnosis") ?? ""),
    });
  }

  return (
    <main className="shell" style={{ paddingBottom: 80 }}>
      <header className="topbar">
        <Link className="brand" href="/dashboard">
          <ArrowLeft size={18} /> Field dashboard
        </Link>
        <span className="eyebrow">
          <Stethoscope size={14} /> Agronomist workspace
        </span>
      </header>
      <div className="page-head" style={{ marginTop: 40 }}>
        <div>
          <h1>Review queue</h1>
          <p className="muted">
            Only your confirmation can promote a scan into the retrieval corpus.
          </p>
        </div>
        <div className="stat">{reviews.data?.length ?? 0}</div>
      </div>
      {error ? (
        <div className="error" role="alert" style={{ marginBottom: 18 }}>
          {error}
        </div>
      ) : null}
      <div className="cards">
        {reviews.isLoading ? (
          <div className="card full empty">
            <LoaderCircle size={28} /> Loading reviews…
          </div>
        ) : null}
        {reviews.data?.map((review) => (
          <section className="card full" key={review.id}>
            <div className="card-head">
              <div>
                <span className="pill">Priority {review.priority_score}</span>
                <h2 style={{ marginTop: 10 }}>{review.reason.replaceAll("_", " ")}</h2>
                <p className="muted">Scan {review.scan_id}</p>
              </div>
              <CheckCircle2 color="#4f8f52" />
            </div>
            <form className="grid-form" onSubmit={(event) => submit(event, review.id)}>
              <div className="field-group">
                <label htmlFor={`decision-${review.id}`}>Decision</label>
                <select
                  className="input"
                  id={`decision-${review.id}`}
                  name="decision"
                  defaultValue="confirmed"
                >
                  <option value="confirmed">Confirm diagnosis</option>
                  <option value="corrected">Correct diagnosis</option>
                  <option value="indeterminate">Indeterminate</option>
                </select>
              </div>
              <div className="field-group" style={{ gridColumn: "span 2" }}>
                <label htmlFor={`diagnosis-${review.id}`}>Confirmed diagnosis</label>
                <input
                  className="input"
                  id={`diagnosis-${review.id}`}
                  name="confirmed_diagnosis"
                  placeholder="Independent agronomist label"
                />
              </div>
              <div className="span-all">
                <button className="button" disabled={decision.isPending} type="submit">
                  Save independent review
                </button>
              </div>
            </form>
          </section>
        ))}
        {reviews.data?.length === 0 ? (
          <div className="card full empty">
            <div>
              <CheckCircle2 size={34} style={{ margin: "0 auto 12px" }} />
              The review queue is clear.
            </div>
          </div>
        ) : null}
      </div>
    </main>
  );
}
