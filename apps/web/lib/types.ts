export interface Problem {
  title: string;
  status: number;
  detail: string;
}

export interface Session {
  organization_id: string;
  role: string;
  expires_in: number;
}

export interface Farm {
  id: string;
  organization_id: string;
  name: string;
  owner_user_id: string | null;
  created_at: string;
}

export interface Field {
  id: string;
  farm_id: string;
  organization_id: string;
  name: string;
  latitude: string;
  longitude: string;
  state: string;
  district: string;
  agro_climatic_zone: string;
  current_crop: "rice" | "wheat" | "tomato" | null;
  created_at: string;
}

export interface CropScore {
  crop: "rice" | "wheat" | "tomato";
  score: number;
  reasons: string[];
}

export interface SoilResult {
  id: string;
  fertility_index: string;
  algorithm_version: string;
  ranked_crops: CropScore[];
  algorithm_sources: string[];
  created_at: string;
}

export interface WeatherAlert {
  alert_type: string;
  severity: "info" | "warning" | "critical";
  message: string;
  source_url: string | null;
}

export interface Forecast {
  source: string;
  fetched_at: string;
  current: {
    observed_at: string;
    temperature_c: number;
    relative_humidity_pct: number | null;
    precipitation_mm: number;
    wind_speed_kph: number;
  };
  alerts: WeatherAlert[];
}

export interface Citation {
  chunk_id: string | null;
  publisher: string;
  title: string;
  page: number | null;
  section: string | null;
  licence: string;
  source_url: string;
  tier: 1 | 2 | 3;
}

export interface Diagnosis {
  image_is_diagnosable: boolean;
  rejection_reason: string | null;
  primary: {
    condition: string;
    category: string;
    confidence: "high" | "moderate" | "low";
    visual_evidence: string;
  } | null;
  differential: Array<{
    condition: string;
    why_considered: string;
    why_less_likely: string;
  }>;
  immediate_actions: string[];
  citations: Citation[];
  requires_expert: boolean;
}

export interface Scan {
  id: string;
  field_id: string;
  status: "pending" | "processing" | "completed" | "rejected" | "failed";
  created_at: string;
  diagnosis: Diagnosis | null;
  failure_code: string | null;
}

export interface AgentAnswer {
  conversation_id: string;
  answer: string;
  citations: Citation[];
}

export interface Review {
  id: string;
  scan_id: string;
  reason: string;
  priority_score: number;
  status: string;
  assigned_to: string | null;
  created_at: string;
}
