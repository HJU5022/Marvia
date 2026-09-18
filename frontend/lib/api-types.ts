// 생성물이다. 손으로 고치지않는다. 고치려면 backend/app/schemas/ 를 고치고 이 스크립트를 다시 돌린다
// scripts/gen_types.sh 가 backend/app/schemas/ 의 Pydantic 모델에서 만듦. API 키 없이 돈다.

export type CandidateKind = "gate" | "lobby" | "landmark" | "pier" | "hq";

export type Preset = "ship_maintenance" | "si_deploy";

export type Stage = "need_confirm" | "need_info" | "done" | "out_of_scope" | "failed";

export type Transport = "car" | "transit" | "walk";

export interface AgentRequest {
  session_id: string | null;
  text: string | null;
  image_base64: string | null;
  preset: Preset | null;
  confirmed_participants: ParticipantInput[] | null;
}

export interface AgentResponse {
  session_id: string;
  stage: Stage;
  slots: Slots | null;
  result: Result | null;
  questions: string[];
  message: string;
  trace_id: string;
  geocoded: GeocodedPin[] | null;
}

export interface Slots {
  preset: Preset | null;
  datetime: string | null;
  purpose: string | null;
  destination: string | null;
  participants: Participant[];
  rendezvous: Rendezvous | null;
  access: Access | null;
  schedule_confirmed: boolean | null;
  constraints: string[];
  missing: string[];
  out_of_scope: boolean;
}

export interface Result {
  candidates: Candidate[];
  provisional: boolean;
  per_participant: ParticipantResult[];
  rendezvous_departure: string | null;
  confidence: number;
  model_small: string;
  model_large: string | null;
  prompt_version: string;
  routed_to: "small" | "large";
}

export interface ParticipantInput {
  name: string;
  lng: number;
  lat: number;
}

export interface ParticipantPatchRequest extends ParticipantInput {
  claim: boolean;
}

export interface ParticipantPatchResponse {
  slots: Slots;
  result: Result | null;
}

export interface GeocodedPin {
  name: string;
  lng: number;
  lat: number;
  confidence: number;
  kind: "participant" | "rendezvous" | "destination" | "pickup";
}

export interface SessionRead {
  id: string;
  preset: string;
  status: string;
  meet_at: string | null;
  purpose: string | null;
  destination_name: string | null;
  destination_lng: number | null;
  destination_lat: number | null;
  participants: Record<string, any>[];
  rendezvous: Record<string, any> | null;
  access: Record<string, any> | null;
  schedule_confirmed: boolean | null;
  constraints: string[];
  created_at: string;
  updated_at: string;
  expires_at: string;
  locked: boolean;
  result: Record<string, any> | null;
}

export interface Access {
  required: boolean;
  applied: boolean | null;
  lead_min: number | null;
}

export interface Candidate {
  name: string;
  kind: CandidateKind;
  address: string;
  lng: number;
  lat: number;
  rank: number | null;
  access_ok: boolean;
  switched_from: string | null;
  reason: string;
  rejected_reason: string | null;
}

export interface Participant {
  name: string;
  origin: string | null;
  transport: Transport | null;
  pickup: string | null;
  pickup_at: string | null;
  unfamiliar: boolean;
  role: "site" | "vendor" | "client" | "colleague";
  owner_user_id: string | null;
}

export interface ParticipantResult {
  name: string;
  candidate_rank: number;
  transport: Transport;
  duration_min: number;
  raw_duration_min: number;
  buffer_min: number;
  departure_time: string;
  arrive_by: string;
  transfer_count: number | null;
  first_train: string | null;
  last_train: string | null;
  polyline: [number, number][];
  via_rendezvous: boolean;
  via_pickup: boolean;
}

export interface Rendezvous {
  name: string;
  transport_after: Transport | null;
}
