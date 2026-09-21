// docs/SDD.md 2·3·4절을 손으로 옮긴 타입.
// backend/app/schemas/ 가 생기고 scripts/gen_types.sh 가 lib/api-types.ts 를 만들면 그 파일로 대체한다.
// SDD 에 없는 필드는 여기에 추가하지 않는다.

export type Preset = "ship_maintenance" | "si_deploy";
export type Transport = "car" | "transit" | "walk";
export type Role = "site" | "vendor" | "client" | "colleague";
export type Stage = "need_confirm" | "need_info" | "done" | "out_of_scope" | "failed";
export type CandidateKind = "gate" | "lobby" | "landmark" | "pier" | "hq";
export type GeocodedPinKind = "participant" | "rendezvous" | "destination" | "pickup";

// 3절 슬롯 스키마

export interface Participant {
  name: string;
  origin: string | null;
  transport: Transport | null;
  pickup: string | null;
  pickup_at: string | null;
  unfamiliar: boolean;
  role: Role;
  owner_user_id: string | null;
}

export interface Rendezvous {
  name: string;
  transport_after: Transport | null;
}

export interface Access {
  required: boolean;
  applied: boolean | null;
  lead_min: number | null;
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

// 4절 결과 스키마

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
  polyline: [number, number][]; // [[lng, lat], ...]
  via_rendezvous: boolean;
  via_pickup: boolean;
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

// 2절 요청·응답

export interface GeocodedPin {
  name: string;
  lng: number;
  lat: number;
  confidence: number;
  kind: GeocodedPinKind;
}

export interface ParticipantInput {
  name: string;
  lng: number;
  lat: number;
}

export interface AgentRequest {
  session_id: string | null;
  text: string | null;
  image_base64: string | null;
  preset: Preset | null;
  confirmed_participants: ParticipantInput[] | null;
}

export interface ParticipantEdit {
  name: string;
  edited_by: string | null;
  edited_at: string | null;
  by_owner: boolean;
}

export interface AgentResponse {
  session_id: string;
  stage: Stage;
  // 추출 전에 끊기면(캡처를 못 읽음, 스키마 위반) null. failed, need_info 에서만 그렇다
  slots: Slots | null;
  result: Result | null;
  questions: string[];
  message: string;
  trace_id: string;
  geocoded: GeocodedPin[] | null;
  edits: ParticipantEdit[] | null;
}

// GET /api/sessions (내 계획 목록)
export interface SessionBrief {
  id: string;
  preset: Preset;
  status: string; // draft / pins_confirmed / computed / failed
  purpose: string | null;
  destination: string | null;
  meet_at: string | null;
  participant_count: number;
  created_at: string;
  expires_at: string;
  locked: boolean;
}

// PATCH /api/session/{id}/participants
export interface ParticipantPatchRequest extends ParticipantInput {
  claim: boolean;
}

// 응답: 갱신된 Slots 와, 재계산이 끝났으면 새 Result
export interface ParticipantPatchResponse {
  slots: Slots;
  result: Result | null;
  edits: ParticipantEdit[] | null;
}
