per # AgriVerse — Production-Grade Architecture, Data Flow & ER Diagram

Companion document to the AgriVerse Production Application Audit & Build Plan. Reflects the resolved decisions: FastAPI + Pydantic, Postgres 17 + pgvector, MinIO AIStor, Redis + ARQ, phone+PIN farmer and staff auth, optional staff OIDC, tiered agronomy corpus, and agronomist-gated retrieval.

---

## 1. Production-Grade Architecture

### 1.1 Component view

```mermaid
graph TB
  subgraph Client["Client Layer"]
    PWA[Next.js PWA<br/>TypeScript, strict]
    ADMIN[Admin / Agronomist console<br/>same Next.js app, role-gated routes]
  end

  subgraph Edge["Delivered by platform team — out of scope"]
    CDN[CDN / WAF]
    LB[Load balancer]
  end

  subgraph App["Application Layer — in scope"]
    NX[Next.js server<br/>SSR, i18n routing]
    API[FastAPI<br/>Pydantic v2, async]
    subgraph APImods["FastAPI modules"]
      AUTHM[auth: phone+PIN, OAuth, RBAC]
      TENM[tenancy: org-scoped repositories]
      AGRM[agronomy: fertility, crop rank, alerts]
      SCANM[scans: upload, diagnosis]
      RETM[retrieval: embed, search, rerank]
      AGENTM[agronomist agent: tools]
      WXM[weather: Open-Meteo provider]
      ADMM[admin: review queue, audit]
    end
    WORKERS[ARQ workers<br/>Python]
  end

  subgraph Data["Pinned Runtime — platform-operated"]
    PG[(Postgres 17 + pgvector<br/>relational + vector, RLS)]
    REDIS[(Redis 7<br/>cache, rate limits, queue broker)]
    MINIO[(MinIO AIStor<br/>S3 API, presigned URLs)]
  end

  subgraph AI["External AI APIs — credentials provisioned"]
    OPENAI[OpenAI<br/>vision, agent, embeddings, reranking]
    GEMINI[Gemini — fallback / cheap gate]
    RETRIEVAL[OpenAI primary / Gemini fallback<br/>separate text vectors + LLM reranking]
  end

  subgraph Ext["External data — free, licensed"]
    OM[Open-Meteo<br/>current conditions and forecasts]
  end

  subgraph Out["Delivered separately by platform team"]
    BILL[Billing / payments]
    OBS[Observability stack]
    IAC[Infra / deployment / IaC]
    CRED[AI credential provisioning]
  end

  PWA --> CDN --> LB --> NX
  ADMIN --> CDN
  NX -->|generated TS client| API
  API --> AUTHM & TENM & AGRM & SCANM & RETM & AGENTM & WXM & ADMM

  API --> PG
  API --> REDIS
  API --> MINIO
  SCANM --> MINIO
  SCANM -->|enqueue| WORKERS
  WORKERS --> REDIS
  WORKERS --> RETRIEVAL
  WORKERS --> PG

  SCANM --> OPENAI
  AGENTM --> OPENAI
  RETM --> RETRIEVAL
  API -.fallback.-> GEMINI

  WXM --> OM

  CRED -.provisions.-> AI
  IAC -.hosts.-> App
  IAC -.hosts.-> Data
  OBS -.observes.-> App
  BILL -.meters via UsageRecord.-> API

  classDef outOfScope fill:#f5f5f5,stroke:#999,stroke-dasharray: 4 3,color:#666
  class Edge,Out outOfScope
```

**Reading this diagram:**
- **Everything inside "Application Layer" is what gets built** in the 10–13 week engagement. Everything greyed out (Edge, Out) is delivered separately by the platform team and only touched at an integration boundary (e.g. `UsageRecord` rows for billing to meter against).
- **Data flows through exactly three platform-operated services** (Postgres, Redis, MinIO) plus AI provider APIs — nothing else needs to be operated by a licensee.
- **The agent (`AGENTM`) and scan diagnosis (`SCANM`) are the only modules that call frontier LLMs directly** — everything else in the app is deterministic Python or retrieval.

### 1.2 Layered / logical view

```mermaid
graph LR
  subgraph L1["Presentation"]
    direction TB
    UI1[Farmer PWA]
    UI2[Staff console]
  end

  subgraph L2["API / Contract"]
    direction TB
    OA[OpenAPI schema]
    TSC[Generated TS client]
  end

  subgraph L3["Domain services"]
    direction TB
    D1[Auth & RBAC]
    D2[Field / Farm / Org]
    D3[Agronomy — pure functions]
    D4[Scan diagnosis]
    D5[Retrieval — image + doc]
    D6[Agronomist agent]
    D7[Weather]
  end

  subgraph L4["Persistence"]
    direction TB
    P1[(Relational tables)]
    P2[(Vector tables)]
    P3[(Object storage)]
    P4[(Cache / queue)]
  end

  subgraph L5["External"]
    direction TB
    E1[LLM providers]
    E2[Embedding provider]
    E3[Weather sources]
  end

  L1 --> L2 --> L3 --> L4
  D4 & D5 & D6 --> E1
  D5 --> E2
  D7 --> E3
```

This is the same system described two ways: §1.1 shows *where data physically moves*; §1.2 shows *what depends on what conceptually* — domain services never call external providers except through the narrow `VisionProvider` / `EmbedProvider` / `WeatherProvider` interfaces defined in the main plan, so any layer can be tested by substituting a fake at that boundary.

---

## 2. Data Flow Diagrams

### 2.1 Scan diagnosis — the core product flow

```mermaid
sequenceDiagram
    actor F as Farmer (PWA)
    participant API as FastAPI
    participant MO as MinIO
    participant W as ARQ Worker
    participant VO as OpenAI / Gemini retrieval
    participant PG as Postgres (pgvector, RLS)
    participant GATE as Cheap model (gate)
    participant VLM as Vision LLM (diagnosis)

    F->>API: POST /scans (request presigned upload)
    API->>API: authz check (org_id from session)
    API->>MO: generate presigned PUT
    API-->>F: presigned URL + scan_id (status=pending)
    F->>MO: PUT image directly
    MO-->>F: 200 OK

    F->>API: POST /scans/{id}/complete
    API->>MO: HEAD object (size, content-type)
    API->>API: validate ≤10MB, MIME sniff, pixel cap
    API->>API: re-encode with Pillow (strip EXIF)
    API->>API: compute SHA-256

    alt SHA-256 seen before
        API->>PG: fetch cached Diagnosis by hash
        API-->>F: return cached diagnosis (near-instant, $0)
    else new image
        API->>GATE: "is this a plant/leaf?"
        alt not diagnosable
            GATE-->>API: image_is_diagnosable=false
            API-->>F: rejection_reason, "retake the photo"
        else diagnosable
            API->>W: enqueue diagnose_scan job
            W->>VO: describe image, embed description in separate provider spaces
            W->>PG: over-fetch similar scans<br/>WHERE org_id = ? AND confirmed_dx IS NOT NULL<br/>LIMIT k*20 (RLS-safe over-fetch)
            PG-->>W: candidate neighbours (post-RLS)
            W->>PG: get field context (crop, region, soil test)
            W->>PG: search_agronomy_docs (tier + region filtered)
            PG-->>W: candidate doc chunks
            W->>VO: rerank(chunks)
            VO-->>W: top-5 chunks
            W->>VLM: diagnose(image, field_ctx, neighbours, cited_chunks)
            VLM-->>W: structured Diagnosis (Pydantic-validated)
            W->>PG: INSERT scan_embedding (confirmed_dx = NULL)
            W->>PG: INSERT diagnosis (full audit fields)
            alt requires_expert OR sampled by information value
                W->>PG: enqueue into agronomist_review_queue
            end
            W-->>API: diagnosis ready (webhook / poll)
        end
        API-->>F: Diagnosis JSON (differential, citations, requires_expert)
    end
```

Key properties this flow enforces:
- **Cost avoidance is structural, not incidental** — SHA-256 cache and the cheap-model gate sit *before* any expensive call, not after.
- **Retrieval happens twice, differently** — image neighbours (accuracy) and document chunks (citation safety) — and both are tenant-filtered with the over-fetch pattern required by RLS + HNSW.
- **The diagnosis is never written as ground truth** — `scan_embedding.confirmed_dx` stays `NULL` until an agronomist confirms it (see §2.2), regardless of how confident the model was.

### 2.2 Agronomist review queue — how a diagnosis becomes retrievable

```mermaid
flowchart TD
    A[New Diagnosis created] --> B{Sampling criteria}
    B -->|low confidence or<br/>requires_expert=true| Q[Enqueue to review queue]
    B -->|no close neighbours found| Q
    B -->|model disagrees with<br/>retrieved neighbours| Q
    B -->|Tier 1 dosage cited| Q
    B -->|none of the above| SKIP[Not queued —<br/>remains unconfirmed]

    F[Farmer submits outcome feedback] --> FB{Outcome}
    FB -->|treatment failed| Q
    FB -->|treatment worked| ANALYTICS[(Product analytics table<br/>— never writes confirmed_dx)]

    Q --> AG[Agronomist reviews in console]
    AG --> DEC{Decision}
    DEC -->|confirmed correct| WRITE[UPDATE scan_embedding<br/>SET confirmed_dx = label]
    DEC -->|corrected| WRITE2[UPDATE scan_embedding<br/>SET confirmed_dx = corrected label]
    DEC -->|indeterminate| DISCARD[Leave confirmed_dx NULL<br/>— never retrievable]

    WRITE --> CORPUS[(Retrievable corpus<br/>confirmed_dx IS NOT NULL)]
    WRITE2 --> CORPUS
    SKIP -.never enters.-> CORPUS
    DISCARD -.never enters.-> CORPUS
    ANALYTICS -.never enters.-> CORPUS

    style CORPUS fill:#d4edda,stroke:#28a745
    style ANALYTICS fill:#fff3cd,stroke:#ffc107
    style SKIP fill:#f8d7da,stroke:#dc3545
    style DISCARD fill:#f8d7da,stroke:#dc3545
```

This is the diagram version of the single most important rule in §C4.2 of the main plan: **there is exactly one write path into the retrievable corpus** — an agronomist's `confirmed_dx` write — and farmer feedback, however useful, only ever routes *toward* that path, never around it.

### 2.3 Document ingestion — building the citation corpus

```mermaid
flowchart LR
    SRC[Source document<br/>ICAR / SAU / CIB&RC] --> LIC{Licence check}
    LIC -->|CC BY-NC — rejected| REJ[Do not ingest]
    LIC -->|GODL-India / CC BY — OK| META[Record: publisher, licence,<br/>source_url, tier, applicable_regions]

    META --> PARSE[Parse<br/>pypdf/pdfplumber, or vision LLM<br/>for scanned bulletins]
    PARSE --> CHUNK[Semantic chunk<br/>~512 tokens, 15% overlap<br/>preserve source/page/section]
    CHUNK --> EMBED[Embed<br/>OpenAI / Gemini text model]
    EMBED --> STORE[(agronomy_document_chunk<br/>tier, applicable_regions, embedding)]

    style REJ fill:#f8d7da,stroke:#dc3545
    style STORE fill:#d4edda,stroke:#28a745
```

At query time (§2.1), retrieval filters on `tier` (a dosage claim requires Tier 1) and `applicable_regions` (a Kerala field never retrieves a Punjab-only document) *before* reranking — both are `WHERE` clauses, not prompt instructions, per the plan's "enforce in the retrieval filter, not the prompt" rule.

### 2.4 Farmer & staff onboarding

```mermaid
flowchart TD
    subgraph Farmer["Farmer path — zero cost"]
        FA[field_agent creates account in person] --> PIN[Sets initial PIN<br/>argon2-hashed]
        PIN --> ACC1[User row: provider=phone]
        SELF[Farmer self-registers] -.optional path.-> ACC1
        ACC1 --> LOGIN1[Phone + PIN login<br/>lockout after 5 failures]
    end

    subgraph Staff["Staff path: PIN or optional OIDC"]
        STAFFPIN[Registered phone + PIN<br/>enabled in production by default] --> CHECKS[Active account and lockout checks]
        CHECKS --> ACC2[Staff account]
        OAUTH[Keycloak / Google / Microsoft via Authlib] --> ACC2
        ACC2 --> LOGIN2[Short access token 15m<br/>+ rotating refresh]
    end

    ACC1 & ACC2 --> USERTBL[(User — single table,<br/>provider discriminator)]
    USERTBL --> MEM[(Membership — org_id + role)]
    MEM --> RBAC{RBAC dependency<br/>per-route}
    RBAC -->|farmer| SCOPE1[Own fields only]
    RBAC -->|field_agent| SCOPE2[Onboard farmers,<br/>reset PINs]
    RBAC -->|agronomist| SCOPE3[Review queue,<br/>confirm diagnoses]
    RBAC -->|org_admin| SCOPE4[Full org access]
```

---

## 3. Entity-Relationship Diagram

```mermaid
erDiagram
    ORGANIZATION ||--o{ MEMBERSHIP : has
    ORGANIZATION ||--o{ FARM : owns
    ORGANIZATION ||--o{ USAGE_RECORD : meters
    ORGANIZATION ||--o{ AUDIT_LOG : scoped_by
    ORGANIZATION ||--o{ AGRONOMIST_REVIEW_QUEUE : scoped_by

    USER ||--o{ MEMBERSHIP : holds
    MEMBERSHIP }o--|| ORGANIZATION : within

    FARM ||--o{ FIELD : contains
    FIELD ||--o{ SOIL_TEST : has
    FIELD ||--o{ SCAN : has
    FIELD ||--o{ CROP_RECOMMENDATION : has
    FIELD ||--o{ WEATHER_SNAPSHOT : has
    FIELD ||--o{ WEATHER_ALERT : triggers
    FIELD {
        uuid id PK
        uuid farm_id FK
        uuid organization_id FK
        string name
        geography location
        string agro_climatic_zone
        string current_crop
        timestamptz created_at
    }

    SCAN ||--o| SCAN_EMBEDDING : produces
    SCAN ||--o| DIAGNOSIS : produces
    SCAN ||--o{ FARMER_OUTCOME_FEEDBACK : receives
    SCAN {
        uuid id PK
        uuid field_id FK
        uuid organization_id FK
        uuid uploaded_by FK
        string object_key
        string sha256
        string status
        timestamptz created_at
    }

    SCAN_EMBEDDING {
        uuid id PK
        uuid scan_id FK
        uuid organization_id FK
        vector embedding "provider-specific description vector, 1024 dimensions"
        text confirmed_dx "NULL until agronomist confirms"
        uuid confirmed_by FK "agronomist User.id"
        timestamptz confirmed_at
        timestamptz created_at
    }

    DIAGNOSIS {
        uuid id PK
        uuid scan_id FK
        uuid organization_id FK
        bool image_is_diagnosable
        string rejection_reason
        jsonb primary_condition
        jsonb differential
        jsonb immediate_actions
        jsonb citations "chunk IDs"
        bool requires_expert
        string provider
        string model_id
        string prompt_version
        jsonb token_usage
        jsonb full_response
        timestamptz created_at
    }

    FARMER_OUTCOME_FEEDBACK {
        uuid id PK
        uuid scan_id FK
        uuid organization_id FK
        string outcome "worked/failed/unsure"
        text notes
        timestamptz created_at
    }

    AGRONOMIST_REVIEW_QUEUE {
        uuid id PK
        uuid scan_id FK
        uuid organization_id FK
        string reason "low_confidence/no_neighbours/disagreement/negative_feedback/tier1_dosage"
        int priority_score
        string status "pending/in_review/resolved"
        uuid assigned_to FK
        timestamptz created_at
        timestamptz resolved_at
    }

    SOIL_TEST {
        uuid id PK
        uuid field_id FK
        uuid organization_id FK
        numeric n
        numeric p
        numeric k
        numeric ph
        numeric ec
        numeric oc
        numeric s
        numeric zn
        numeric fe
        numeric cu
        numeric mn
        numeric b
        numeric fertility_index "computed, not stored duplicate of logic"
        timestamptz created_at
    }

    CROP_RECOMMENDATION {
        uuid id PK
        uuid field_id FK
        uuid organization_id FK
        uuid soil_test_id FK
        jsonb ranked_crops
        timestamptz created_at
    }

    WEATHER_SNAPSHOT {
        uuid id PK
        uuid field_id FK
        string source "open-meteo"
        jsonb forecast_dto
        timestamptz fetched_at
    }

    WEATHER_ALERT {
        uuid id PK
        uuid field_id FK
        string alert_type
        string severity
        jsonb payload
        timestamptz created_at
    }

    AGRONOMY_DOCUMENT ||--o{ AGRONOMY_DOCUMENT_CHUNK : chunked_into
    AGRONOMY_DOCUMENT {
        uuid id PK
        string publisher
        string licence
        string source_url
        int tier "1=regulatory 2=practice 3=identification"
        jsonb applicable_regions "null=national"
        timestamptz retrieved_at
        timestamptz created_at
    }

    AGRONOMY_DOCUMENT_CHUNK {
        uuid id PK
        uuid document_id FK
        int page_number
        string section
        text content
        vector embedding "provider-specific text vector, 1024 dimensions"
    }

    USAGE_RECORD {
        uuid id PK
        uuid organization_id FK
        string call_type "scan_diagnosis/gate/agent/embed"
        int tokens_used
        numeric cost_usd
        timestamptz created_at
    }

    AUDIT_LOG {
        uuid id PK
        uuid organization_id FK
        uuid actor_user_id FK
        string action
        jsonb before
        jsonb after
        timestamptz created_at
    }

    USER {
        uuid id PK
        string provider "phone/oauth"
        string phone_e164 "nullable, unique"
        string oauth_subject "nullable, unique"
        string pin_hash "argon2, nullable"
        string preferred_language
        int failed_login_attempts
        timestamptz locked_until
        timestamptz created_at
    }

    MEMBERSHIP {
        uuid id PK
        uuid user_id FK
        uuid organization_id FK
        string role "farmer/field_agent/agronomist/org_admin/support/super_admin"
        timestamptz created_at
    }

    ORGANIZATION {
        uuid id PK
        string name
        string licence_tier
        timestamptz created_at
    }

    FARM {
        uuid id PK
        uuid organization_id FK
        string name
        timestamptz created_at
    }
```

### 3.1 Notes on the schema

- **Every tenant-scoped table carries `organization_id` directly**, even where it's technically derivable through a join (e.g. `SCAN_EMBEDDING` could derive org via `SCAN`). This is deliberate redundancy: RLS policies apply a flat `organization_id = current_setting('app.org_id')` predicate on each table independently, which is what makes the raw-SQL vector queries in §2.1 safe without relying on join correctness at query time.
- **`SCAN_EMBEDDING.confirmed_dx` is nullable by design** — its nullability *is* the corpus-membership gate described in §2.2, enforced at the query level (`WHERE confirmed_dx IS NOT NULL`) rather than via a separate boolean flag that could drift out of sync.
- **`DIAGNOSIS` is deliberately wide and denormalized** (`full_response`, `token_usage` as JSONB) — this table is the audit trail for dispute resolution and eval regression, so it intentionally keeps more than a normalized schema would, per the plan's "every diagnosis logged... for review, dispute resolution and eval regression" control.
- **`AGRONOMY_DOCUMENT.tier` and `applicable_regions` are `NOT NULL` at the document level**, not the chunk level — tier and licensing are properties of the source document, not of an individual chunk, so this avoids re-deriving them per chunk at retrieval time.
- **`FARMER_OUTCOME_FEEDBACK` is intentionally a separate table from `SCAN_EMBEDDING`**, not a column on it — this is the schema-level enforcement of "farmer feedback never writes `confirmed_dx` directly" from §2.2; the two tables can only be joined, never conflated.
- **`vector` column dimensions are placeholders ("dim N")** — use the configured 1024 dimensions for both separate provider columns and pin the schema dimension; changing it later requires re-embedding the full corpus, as noted in the main plan.
