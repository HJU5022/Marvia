/** Wire contracts transcribed from backend/app/schemas/agent.py (2026-09-28, sale_due_date 선택 입력은 10-01 반영).
 * Dates/datetimes serialize as ISO strings. Nullable required fields stay required.
 * Python defaulted fields are optional on request, populated on serialized response.
 * History contracts come from backend/app/routers/history.py, not the mockup.
 */
export type Verdict = 'fine' | 'watch' | 'act';
export type Status = 'ok' | 'partial' | 'insufficient' | 'failed' | 'unsupported';
export type VesselMatch = 'confirmed' | 'uncertain' | 'none';
export type Freshness = 'fresh' | 'stale' | 'unknown';
export interface AgentRequest {
  bl_no: string;
  bl_type: 'MASTER' | 'HOUSE';
  // 선택 입력 (09-29 계약 변경). 없으면 null로 보내고 백엔드는 배 상태만으로 판정한다
  sale_due_date: string | null;
  session_id: string;
  follow_up_question?: string | null;
  resolved_mmsi?: number | null;
  voyage_no?: string | null;
  forwarder_eta?: string | null;
}
export interface Evidence {
  source: 'shipfinder' | 'unipass' | 'mof' | 'searoute' | 'rule';
  field: string; value: string; fetched_at: string;
}
export interface Reason { rule: string; value: string; triggered: boolean }
export interface Conflict { signals: string[]; chosen: string; why: string }
export interface VesselCandidate {
  mmsi: number; imo: number | null; name: string; flag: string | null;
  dest: string | null; last_time: string; ship_type: number | null; match_reasons: string[];
}
export interface VesselInfo {
  mmsi: number; imo: number | null; name: string; call_sign: string | null;
  flag: string | null; ship_type: number | null; voyage_no: string | null;
}
export interface Position {
  lat: number; lng: number; sog: number; cog: number; navistat: number;
  last_time: string; freshness: Freshness;
}
export interface EtaInfo {
  ais_eta: string | null; mof_eta: string | null; calc_eta: string | null;
  trusted_eta: string | null; distance_nm: number | null;
}
export interface CustomsInfo {
  stage_code: string; stage_name: string; plain_explanation: string;
  next_stage: string | null; needs_broker: boolean;
  // Backend is list[dict], not a stronger invented timeline contract.
  history: Record<string, unknown>[];
}
export interface BerthInfo { facility: string | null; shed: string | null }
export interface AgentResponse {
  status: Status; verdict: Verdict | null; vessel_match: VesselMatch;
  vessel_candidates: VesselCandidate[]; missing_inputs: string[]; reasons: Reason[];
  conflicts: Conflict[]; actions: string[]; days_margin: number | null;
  decided_by: 'rule' | 'llm' | null; vessel: VesselInfo | null;
  position: Position | null; eta: EtaInfo | null; customs: CustomsInfo | null;
  berth: BerthInfo | null; evidence: Evidence[]; answer: string; trace_id: string;
}
export interface HistoryItem {
  request_id: string | null; bl_masked: string | null; status: string | null;
  verdict: string | null; vessel_match: string | null; decided_by: 'rule' | 'llm' | null;
  model: string | null; trace_id: string | null; created_at: string;
}
export interface HistoryResponse { items: HistoryItem[]; available: boolean }

/** POST /api/document 응답. backend/app/schemas/document.py 그대로 (C1~C8 밖의 새 계약, 09-29). */
export type DocumentCheck = 'missing' | 'not_in_text' | 'format' | 'ambiguous';
export interface DocumentField { value: string | null; checks: DocumentCheck[] }
export interface DocumentResponse {
  status: 'ok' | 'partial';
  needs_review: boolean;
  fields: Record<'bl_no' | 'vessel' | 'voyage' | 'eta' | 'pol' | 'pod' | 'item', DocumentField>;
  ocr: { lines: number; rotation: 0 | 180 | 270; runs: number; ocr_ms: number };
  trace_id: string;
}

/** 운영자 관리 (backend/app/routers/admin.py, docs/specs/operator-admin.md, 10-01). */
export interface MeResponse { user_id: string | null; email: string | null; is_operator: boolean; profile_complete: boolean }
/** 본인 회원 정보 (GET·PUT /api/profile, docs/specs/user-profile.md). 본인에게만 원문 */
export interface ProfileData { name: string; phone: string; address: string }
export interface CustomerItem {
  user_id: string; email_masked: string | null; name_masked: string | null;
  phone_masked: string | null; address_masked: string | null; profile_complete: boolean;
  created_at: string | null; last_sign_in_at: string | null; is_operator: boolean;
}
export interface CustomersResponse { items: CustomerItem[]; total: number }
export interface OperatorItem { email: string; granted_by: string; granted_at: string }
export interface AuditItem { action: 'grant' | 'revoke'; target_email: string; actor_user_id: string; actor_email: string | null; created_at: string }
export interface OperatorsResponse { operators: OperatorItem[]; audit: AuditItem[] }
/** 운영자의 고객 동작 (operator-admin 추가 절). 마스킹 해제는 사유를 남기고 한 명만 원문 */
export interface UnmaskResponse { email: string | null; name: string | null; phone: string | null; address: string | null }
export interface ActionItem {
  action: 'customer_update' | 'customer_delete' | 'unmask'; target_user_id: string; target_email_masked: string | null;
  actor_user_id: string; actor_email: string | null; reason: string | null; created_at: string;
}
