"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  ChevronRight,
  CloudSun,
  FlaskConical,
  LayoutDashboard,
  Leaf,
  LoaderCircle,
  LogOut,
  MapPin,
  MessageCircle,
  Plus,
  ScanLine,
  Sprout,
  Stethoscope,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  FormEvent,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, ApiError } from "@/lib/api";
import { uploadScanImage } from "@/lib/scan-upload";
import type {
  AgentAnswer,
  Farm,
  Field,
  Forecast,
  Scan,
  SoilResult,
} from "@/lib/types";

type Section = "overview" | "soil" | "scan" | "agent";

function SectionButton({
  active,
  icon,
  children,
  onClick,
}: {
  active: boolean;
  icon: ReactNode;
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button className={`side-link ${active ? "active" : ""}`} onClick={onClick}>
      {icon}
      {children}
    </button>
  );
}

function SetupCard({
  farms,
  onCreated,
}: {
  farms: Farm[];
  onCreated: () => void;
}) {
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submitFarm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      await api<Farm>("farms", {
        method: "POST",
        body: JSON.stringify({ name: form.get("name"), owner_user_id: null }),
      });
      event.currentTarget.reset();
      onCreated();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not create farm");
    } finally {
      setPending(false);
    }
  }

  async function submitField(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      await api<Field>("fields", {
        method: "POST",
        body: JSON.stringify({
          farm_id: form.get("farm_id"),
          name: form.get("name"),
          latitude: form.get("latitude"),
          longitude: form.get("longitude"),
          state: form.get("state"),
          district: form.get("district"),
          agro_climatic_zone: form.get("agro_climatic_zone"),
          current_crop: form.get("current_crop") || null,
        }),
      });
      event.currentTarget.reset();
      onCreated();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not create field");
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="card full">
      <div className="card-head">
        <div>
          <h2>{farms.length ? "Add your first field" : "Create your farm record"}</h2>
          <p className="muted">
            This becomes the home for soil tests, scans, weather, and recommendations.
          </p>
        </div>
        <span className="icon-box">
          <Plus size={20} />
        </span>
      </div>
      {farms.length === 0 ? (
        <form className="form" onSubmit={submitFarm}>
          <div className="field-group">
            <label htmlFor="farm-name">Farm name</label>
            <input
              className="input"
              id="farm-name"
              name="name"
              placeholder="My family farm"
              required
            />
          </div>
          <button className="button" disabled={pending} type="submit">
            Create farm
          </button>
        </form>
      ) : (
        <form className="grid-form" onSubmit={submitField}>
          <div className="field-group">
            <label htmlFor="farm_id">Farm</label>
            <select className="input" id="farm_id" name="farm_id" required>
              {farms.map((farm) => (
                <option key={farm.id} value={farm.id}>
                  {farm.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field-group">
            <label htmlFor="field-name">Field name</label>
            <input className="input" id="field-name" name="name" required />
          </div>
          <div className="field-group">
            <label htmlFor="current_crop">Current crop</label>
            <select className="input" id="current_crop" name="current_crop">
              <option value="">Not planted</option>
              <option value="rice">Rice</option>
              <option value="wheat">Wheat</option>
              <option value="tomato">Tomato</option>
            </select>
          </div>
          <div className="field-group">
            <label htmlFor="latitude">Latitude</label>
            <input
              className="input"
              id="latitude"
              name="latitude"
              type="number"
              step="0.000001"
              required
            />
          </div>
          <div className="field-group">
            <label htmlFor="longitude">Longitude</label>
            <input
              className="input"
              id="longitude"
              name="longitude"
              type="number"
              step="0.000001"
              required
            />
          </div>
          <div className="field-group">
            <label htmlFor="state">State</label>
            <input className="input" id="state" name="state" required />
          </div>
          <div className="field-group">
            <label htmlFor="district">District</label>
            <input className="input" id="district" name="district" required />
          </div>
          <div className="field-group">
            <label htmlFor="zone">Agro-climatic zone</label>
            <input className="input" id="zone" name="agro_climatic_zone" required />
          </div>
          <div className="span-all">
            <button className="button" disabled={pending} type="submit">
              Add field
            </button>
          </div>
        </form>
      )}
      {error ? (
        <div className="error" role="alert" style={{ marginTop: 14 }}>
          {error}
        </div>
      ) : null}
    </section>
  );
}

function SoilPanel({ fieldId }: { fieldId: string }) {
  const [result, setResult] = useState<SoilResult | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const nutrients = ["n", "p", "k", "ph", "ec", "oc", "s", "zn", "fe", "cu", "mn", "b"];
  const defaults: Record<string, string> = {
    n: "350",
    p: "32",
    k: "210",
    ph: "6.5",
    ec: "0.7",
    oc: "0.9",
    s: "14",
    zn: "0.8",
    fe: "6",
    cu: "0.4",
    mn: "3",
    b: "0.7",
  };

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const payload = Object.fromEntries(
      nutrients.map((nutrient) => [nutrient, form.get(nutrient)]),
    );
    try {
      setResult(
        await api<SoilResult>(`fields/${fieldId}/soil-tests`, {
          method: "POST",
          body: JSON.stringify(payload),
        }),
      );
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not save soil test");
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <section className="card wide">
        <div className="card-head">
          <div>
            <h2>Record a soil test</h2>
            <p className="muted">Enter the values exactly as shown on the lab report.</p>
          </div>
          <span className="icon-box">
            <FlaskConical size={20} />
          </span>
        </div>
        <form className="grid-form" onSubmit={submit}>
          {nutrients.map((nutrient) => (
            <div className="field-group" key={nutrient}>
              <label htmlFor={nutrient}>{nutrient.toUpperCase()}</label>
              <input
                className="input"
                defaultValue={defaults[nutrient]}
                id={nutrient}
                min="0"
                name={nutrient}
                step="0.01"
                type="number"
                required
              />
            </div>
          ))}
          <div className="span-all">
            <button className="button" disabled={pending} type="submit">
              {pending ? <LoaderCircle size={17} /> : <FlaskConical size={17} />}
              Calculate and save
            </button>
          </div>
        </form>
        {error ? (
          <div className="error" role="alert" style={{ marginTop: 14 }}>
            {error}
          </div>
        ) : null}
      </section>
      <section className="card">
        <h2>Result</h2>
        {result ? (
          <>
            <p className="stat" style={{ margin: "26px 0 5px" }}>
              {result.fertility_index}
            </p>
            <p className="muted">Deterministic fertility index</p>
            <div className="crop-bars">
              {result.ranked_crops.map((crop) => (
                <div key={crop.crop}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <strong style={{ textTransform: "capitalize" }}>{crop.crop}</strong>
                    <span>{crop.score}%</span>
                  </div>
                  <div className="bar-track">
                    <div className="bar-fill" style={{ width: `${crop.score}%` }} />
                  </div>
                </div>
              ))}
            </div>
            <details style={{ marginTop: 18 }}>
              <summary>Algorithm evidence and version</summary>
              <p className="muted">Version {result.algorithm_version}</p>
              <ul>
                {result.algorithm_sources.map((source) => (
                  <li key={source}>
                    <a href={source} rel="noreferrer" target="_blank">
                      Government or agricultural-university source
                    </a>
                  </li>
                ))}
              </ul>
            </details>
          </>
        ) : (
          <div className="empty">Your calculated score and crop ranking will appear here.</div>
        )}
      </section>
    </>
  );
}

function ScanPanel({ fieldId }: { fieldId: string }) {
  const [file, setFile] = useState<File | null>(null);
  const [scanId, setScanId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);

  const scan = useQuery({
    queryKey: ["scan", scanId],
    queryFn: () => api<Scan>(`scans/${scanId}`),
    enabled: Boolean(scanId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "processing" ? 2500 : false;
    },
  });

  async function upload() {
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const created = await api<{
        scan_id: string;
        upload_url: string;
        required_headers: Record<string, string>;
      }>(`fields/${fieldId}/scans`, {
        method: "POST",
        body: JSON.stringify({ filename: file.name, content_type: file.type }),
      });
      await uploadScanImage(created.upload_url, created.required_headers, file);
      await api(`scans/${created.scan_id}/complete`, {
        method: "POST",
        idempotency: true,
      });
      setScanId(created.scan_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  const diagnosis = scan.data?.diagnosis;
  return (
    <>
      <section className="card">
        <div className="card-head">
          <h2>New plant scan</h2>
          <span className="icon-box">
            <ScanLine size={20} />
          </span>
        </div>
        <label className="dropzone">
          <div>
            <Upload size={30} style={{ margin: "0 auto 12px" }} />
            <strong>{file ? file.name : "Choose a clear plant photo"}</strong>
            <p className="muted">JPEG, PNG, or WebP · maximum 10 MB</p>
          </div>
          <input
            accept="image/jpeg,image/png,image/webp"
            hidden
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            type="file"
          />
        </label>
        <button
          className="button"
          disabled={!file || uploading}
          onClick={upload}
          style={{ width: "100%", marginTop: 14 }}
        >
          {uploading ? <LoaderCircle size={17} /> : <ScanLine size={17} />}
          Upload and diagnose
        </button>
        {error ? (
          <div className="error" role="alert" style={{ marginTop: 12 }}>
            {error}
          </div>
        ) : null}
      </section>
      <section className="card wide">
        <div className="card-head">
          <h2>Diagnosis</h2>
          {scan.data ? <span className="pill">{scan.data.status}</span> : null}
        </div>
        {scan.isFetching && !diagnosis ? (
          <div className="empty">
            <div>
              <LoaderCircle size={28} style={{ margin: "0 auto 10px" }} />
              Validating and reviewing the image…
            </div>
          </div>
        ) : diagnosis ? (
          <div className="diagnosis" aria-live="polite">
            {diagnosis.image_is_diagnosable && diagnosis.primary ? (
              <div className="diagnosis-primary">
                <span className="pill">{diagnosis.primary.confidence} confidence</span>
                <h3 style={{ fontSize: "1.7rem", marginTop: 12 }}>
                  {diagnosis.primary.condition}
                </h3>
                <p style={{ color: "rgb(255 255 255 / 72%)" }}>
                  {diagnosis.primary.visual_evidence}
                </p>
              </div>
            ) : (
              <div className="error">{diagnosis.rejection_reason}</div>
            )}
            {diagnosis.immediate_actions.length ? (
              <div>
                <h3>Immediate actions</h3>
                <ul>
                  {diagnosis.immediate_actions.map((action) => (
                    <li key={action}>{action}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {diagnosis.differential.length ? (
              <div>
                <h3>Differential</h3>
                {diagnosis.differential.map((alternative) => (
                  <p key={alternative.condition}>
                    <strong>{alternative.condition}:</strong> {alternative.why_considered}
                  </p>
                ))}
              </div>
            ) : null}
            {diagnosis.requires_expert ? (
              <div className="alert">
                This result has been routed to an agronomist for review.
              </div>
            ) : null}
          </div>
        ) : scan.data?.status === "failed" ? (
          <div className="error">Diagnosis failed: {scan.data.failure_code}</div>
        ) : (
          <div className="empty">Upload a photo to receive a structured diagnosis.</div>
        )}
      </section>
    </>
  );
}

function AgentPanel({ fieldId }: { fieldId: string }) {
  const [question, setQuestion] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Array<{ role: "user" | "assistant"; text: string }>>(
    [],
  );
  const [error, setError] = useState("");
  const mutation = useMutation({
    mutationFn: (text: string) =>
      api<AgentAnswer>("agronomist/ask", {
        method: "POST",
        body: JSON.stringify({
          field_id: fieldId,
          conversation_id: conversationId,
          question: text,
          language: "en",
        }),
      }),
    onSuccess: (answer) => {
      setConversationId(answer.conversation_id);
      setMessages((current) => [...current, { role: "assistant", text: answer.answer }]);
    },
    onError: (reason) =>
      setError(reason instanceof ApiError ? reason.message : "Assistant unavailable"),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    const text = question.trim();
    setMessages((current) => [...current, { role: "user", text }]);
    setQuestion("");
    setError("");
    mutation.mutate(text);
  }

  return (
    <section className="card full">
      <div className="card-head">
        <div>
          <h2>Ask the field agronomist</h2>
          <p className="muted">
            Answers use this field’s soil, scans, weather, and licensed references.
          </p>
        </div>
        <span className="icon-box">
          <Bot size={20} />
        </span>
      </div>
      <div className="agent-thread" aria-live="polite">
        {messages.length === 0 ? (
          <div className="empty">
            Ask “Why are my tomato leaves yellowing?” or “Should I irrigate tomorrow?”
          </div>
        ) : (
          messages.map((message, index) => (
            <div className={`bubble ${message.role}`} key={`${message.role}-${index}`}>
              {message.text}
            </div>
          ))
        )}
        {mutation.isPending ? (
          <div className="bubble assistant">Reviewing the field record and sources…</div>
        ) : null}
      </div>
      <form onSubmit={submit} style={{ display: "flex", gap: 10 }}>
        <input
          className="input"
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about this field…"
          value={question}
        />
        <button className="button" disabled={mutation.isPending} type="submit">
          <MessageCircle size={17} /> Ask
        </button>
      </form>
      {error ? (
        <div className="error" role="alert" style={{ marginTop: 12 }}>
          {error}
        </div>
      ) : null}
    </section>
  );
}

export function DashboardClient({ role }: { role: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [section, setSection] = useState<Section>("overview");
  const [selectedFieldId, setSelectedFieldId] = useState<string>("");

  const farms = useQuery({ queryKey: ["farms"], queryFn: () => api<Farm[]>("farms") });
  const fields = useQuery({ queryKey: ["fields"], queryFn: () => api<Field[]>("fields") });

  useEffect(() => {
    if (!selectedFieldId && fields.data?.length) {
      setSelectedFieldId(fields.data[0].id);
    }
  }, [fields.data, selectedFieldId]);

  const selectedField = useMemo(
    () => fields.data?.find((field) => field.id === selectedFieldId),
    [fields.data, selectedFieldId],
  );

  const weather = useQuery({
    queryKey: ["weather", selectedFieldId],
    queryFn: () => api<Forecast>(`fields/${selectedFieldId}/weather`),
    enabled: Boolean(selectedFieldId),
    staleTime: 10 * 60 * 1000,
  });
  const soil = useQuery({
    queryKey: ["soil", selectedFieldId],
    queryFn: () => api<SoilResult>(`fields/${selectedFieldId}/soil-tests/latest`),
    enabled: Boolean(selectedFieldId),
    retry: false,
  });

  async function logout() {
    await fetch("/api/logout", { method: "POST" });
    router.push("/");
    router.refresh();
  }

  function refreshSetup() {
    void queryClient.invalidateQueries({ queryKey: ["farms"] });
    void queryClient.invalidateQueries({ queryKey: ["fields"] });
  }

  return (
    <div className="dashboard">
      <aside className="sidebar">
        <Link className="brand" href="/" style={{ color: "white" }}>
          <span className="brand-mark" style={{ background: "white", color: "#103d2a" }}>
            <Sprout size={20} />
          </span>
          AgriVerse
        </Link>
        <nav className="side-nav" aria-label="Field workspace">
          <SectionButton
            active={section === "overview"}
            icon={<LayoutDashboard size={18} />}
            onClick={() => setSection("overview")}
          >
            Overview
          </SectionButton>
          <SectionButton
            active={section === "soil"}
            icon={<FlaskConical size={18} />}
            onClick={() => setSection("soil")}
          >
            Soil & crops
          </SectionButton>
          <SectionButton
            active={section === "scan"}
            icon={<ScanLine size={18} />}
            onClick={() => setSection("scan")}
          >
            Plant scan
          </SectionButton>
          <SectionButton
            active={section === "agent"}
            icon={<MessageCircle size={18} />}
            onClick={() => setSection("agent")}
          >
            Ask agronomist
          </SectionButton>
          {role === "agronomist" || role === "org_admin" ? (
            <Link className="side-link" href="/staff/reviews">
              <Stethoscope size={18} /> Review queue
            </Link>
          ) : null}
        </nav>
        <div className="side-footer">
          <button className="side-link" onClick={logout}>
            <LogOut size={18} /> Sign out
          </button>
        </div>
      </aside>

      <main className="dashboard-main">
        <header className="page-head">
          <div>
            <p className="eyebrow">
              <Leaf size={14} /> Living field record
            </p>
            <h1>{selectedField?.name ?? "Your fields"}</h1>
            <p className="muted">
              {selectedField
                ? `${selectedField.district}, ${selectedField.state} · ${
                    selectedField.current_crop ?? "No crop selected"
                  }`
                : "Add a field to begin building its history."}
            </p>
          </div>
          {fields.data?.length ? (
            <select
              aria-label="Selected field"
              className="input"
              onChange={(event) => setSelectedFieldId(event.target.value)}
              style={{ width: 240 }}
              value={selectedFieldId}
            >
              {fields.data.map((field) => (
                <option key={field.id} value={field.id}>
                  {field.name}
                </option>
              ))}
            </select>
          ) : null}
        </header>

        <div className="cards">
          {!fields.isLoading && fields.data?.length === 0 ? (
            <SetupCard farms={farms.data ?? []} onCreated={refreshSetup} />
          ) : null}

          {selectedField && section === "overview" ? (
            <>
              <section className="card">
                <div className="card-head">
                  <h2>Soil health</h2>
                  <span className="icon-box">
                    <FlaskConical size={20} />
                  </span>
                </div>
                {soil.data ? (
                  <>
                    <p className="stat" style={{ margin: "30px 0 7px" }}>
                      {soil.data.fertility_index}
                    </p>
                    <p className="muted">Latest deterministic index</p>
                  </>
                ) : (
                  <div className="empty">No soil test yet</div>
                )}
                <button className="button secondary" onClick={() => setSection("soil")}>
                  Record soil test <ChevronRight size={16} />
                </button>
              </section>
              <section className="card">
                <div className="card-head">
                  <h2>Weather now</h2>
                  <span className="icon-box">
                    <CloudSun size={20} />
                  </span>
                </div>
                {weather.data ? (
                  <>
                    <p className="stat" style={{ margin: "30px 0 7px" }}>
                      {weather.data.current.temperature_c.toFixed(0)}°
                    </p>
                    <p className="muted">
                      {weather.data.current.relative_humidity_pct ?? "—"}% humidity ·{" "}
                      {weather.data.current.wind_speed_kph.toFixed(0)} km/h wind
                    </p>
                    {weather.data.alerts.map((alert) => (
                      <div className="alert" key={alert.alert_type}>
                        {alert.message}{" "}
                        {alert.source_url ? (
                          <a href={alert.source_url} rel="noreferrer" target="_blank">
                            Criteria
                          </a>
                        ) : null}
                      </div>
                    ))}
                  </>
                ) : (
                  <div className="empty">Weather unavailable</div>
                )}
              </section>
              <section className="card">
                <div className="card-head">
                  <h2>Field location</h2>
                  <span className="icon-box">
                    <MapPin size={20} />
                  </span>
                </div>
                <h3 style={{ marginTop: 28 }}>{selectedField.agro_climatic_zone}</h3>
                <p className="muted">
                  Advice is filtered to this zone or national guidance.
                </p>
              </section>
              <section className="card full">
                <div className="card-head">
                  <div>
                    <h2>What would you like to do?</h2>
                    <p className="muted">Each action adds context to this field record.</p>
                  </div>
                </div>
                <div className="field-list">
                  {[
                    {
                      label: "Scan a plant symptom",
                      detail: "Upload a clear field photo for a structured diagnosis",
                      target: "scan" as Section,
                    },
                    {
                      label: "Add soil laboratory values",
                      detail: "Calculate fertility and rank crop suitability",
                      target: "soil" as Section,
                    },
                    {
                      label: "Ask a field-aware question",
                      detail: "Use soil, weather, scans, and cited references together",
                      target: "agent" as Section,
                    },
                  ].map((action) => (
                    <button
                      className="field-row"
                      key={action.target}
                      onClick={() => setSection(action.target)}
                    >
                      <span>
                        <strong>{action.label}</strong>
                        <small>{action.detail}</small>
                      </span>
                      <ChevronRight size={18} />
                    </button>
                  ))}
                </div>
              </section>
            </>
          ) : null}

          {selectedField && section === "soil" ? (
            <SoilPanel fieldId={selectedField.id} />
          ) : null}
          {selectedField && section === "scan" ? (
            <ScanPanel fieldId={selectedField.id} />
          ) : null}
          {selectedField && section === "agent" ? (
            <AgentPanel fieldId={selectedField.id} />
          ) : null}
        </div>
      </main>
    </div>
  );
}
