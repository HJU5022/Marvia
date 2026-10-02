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
  /** 적하목록 관리번호. 세관에 아직 없는 화물을 해수부 입항 신고로 찾을 때 (docs/specs/mrn-fallback.md) */
  mrn?: string | null;
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
  /** 어디서 어디로 (UNI-PASS 적재항·양륙항, 10-01). 없으면 null */
  loading_port?: string | null; loading_port_name?: string | null; loading_country?: string | null;
  discharge_port?: string | null; discharge_port_name?: string | null;
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
/** B/L 조건 세 칸·인코텀즈·화물 인도 연락처 (10-02 결정 6). 서류에 없으면 value null, checks 빈 목록 */
export type DocumentConditionKey = 'original_bl' | 'to_order_bank' | 'freight_term' | 'incoterm'
  | 'contact_company' | 'contact_role' | 'contact_phone';
export type DocumentFieldKey = 'bl_no' | 'vessel' | 'voyage' | 'eta' | 'pol' | 'pod' | 'item' | DocumentConditionKey;
export interface DocumentResponse {
  status: 'ok' | 'partial';
  needs_review: boolean;
  fields: Record<DocumentFieldKey, DocumentField>;
  ocr: { lines: number; rotation: 0 | 180 | 270; runs: number; ocr_ms: number };
  trace_id: string;
  /** 서류의 MRN (코드가 뽑음). 없으면 null */
  mrn?: string | null;
  /** 서류 종류. 거래처를 기억할 때 출처로 쓴다. 모르면 null (10-02) */
  doc_kind?: 'B/L' | 'A/N' | null;
}

/** 화물 비서 기억 (backend/app/schemas/memory.py, docs/specs/memory.md, 10-02). 원본 B/L은 오지 않는다 */
export type ContactRole = '포워더' | '관세사' | '수출자' | '판매처';
export type OriginalBl = 'required' | 'surrendered';
export type FreightTerm = 'prepaid' | 'collect';
export type Incoterm = 'CIF' | 'FOB' | 'CFR';
export type MemoryKind = 'preference' | 'schedule' | 'contact' | 'worry' | 'todo';
export interface MemoryItem {
  id: string; section: 'about' | 'cargo'; kind: MemoryKind;
  fields: Record<string, string | boolean | null>; noted_at: string | null;
  /** 화물별 항목의 화물 이름(이름표 또는 가린 번호). 이 사람에 대해 항목은 null */
  cargo_name: string | null;
}
export interface PendingChange { field: 'sale_due_date' | 'forwarder_eta' | 'label'; value: string; noted_at: string | null }
export interface CargoSummary {
  bl_masked: string; bl_type: 'MASTER' | 'HOUSE'; label: string | null; status: 'active' | 'done';
  sale_due_date: string | null; forwarder_eta: string | null;
  original_bl: OriginalBl | null; to_order_bank: boolean | null; freight_term: FreightTerm | null; incoterm: Incoterm | null;
  last_verdict: Verdict | null; last_checked_at: string | null; last_days_margin: number | null;
  last_eta: string | null; last_stage: string | null; pending: PendingChange[]; summary: string | null;
}
export interface MemoryResponse {
  markdown: string; items: MemoryItem[]; cargo: CargoSummary[];
  /** 상한을 넘어 새 기억을 저장하지 못했다 (EC-06) */
  full: boolean; available: boolean;
}
/** POST /api/memory/document-facts. 서류 확인 화면에서 사용자가 확인한 값만 보낸다 (10-02 결정 7) */
export interface DocumentFactsRequest {
  bl_no: string; bl_type?: 'MASTER' | 'HOUSE' | null; source?: 'B/L' | 'A/N' | null;
  original_bl?: OriginalBl | null; to_order_bank?: boolean | null; freight_term?: FreightTerm | null; incoterm?: Incoterm | null;
  contact?: {company: string; role: ContactRole; phone: string | null} | null;
}
export interface DocumentFactsResponse {
  conditions_saved: boolean;
  contact: 'saved' | 'unchanged' | 'rejected' | 'skipped' | 'full' | 'conflict';
}

/** 운영자 관리 (backend/app/routers/admin.py, docs/specs/operator-admin.md, 10-01). */
export interface MeResponse { user_id: string | null; email: string | null; is_operator: boolean; profile_complete: boolean;
  /** 화면 전용. 서버가 403 account_suspended를 주면 true (operator-admin 일시 정지) */
  suspended?: boolean }
/** 본인 회원 정보 (GET·PUT /api/profile, docs/specs/user-profile.md). 본인에게만 원문 */
export interface ProfileData { name: string; phone: string; address: string }
export interface CustomerItem {
  user_id: string; email_masked: string | null; name_masked: string | null;
  phone_masked: string | null; address_masked: string | null; profile_complete: boolean; is_suspended: boolean;
  created_at: string | null; last_sign_in_at: string | null; is_operator: boolean;
}
export interface CustomersResponse { items: CustomerItem[]; total: number }
export interface OperatorItem { email: string; granted_by: string; granted_at: string }
export interface AuditItem { action: 'grant' | 'revoke'; target_email: string; actor_user_id: string; actor_email: string | null; created_at: string }
export interface OperatorsResponse { operators: OperatorItem[]; audit: AuditItem[] }
/** 운영자의 고객 동작 (operator-admin 추가 절). 마스킹 해제는 사유를 남기고 한 명만 원문 */
export interface UnmaskResponse { email: string | null; name: string | null; phone: string | null; address: string | null }
export interface ActionItem {
  action: 'customer_update' | 'customer_delete' | 'unmask' | 'customer_suspend' | 'customer_resume'; target_user_id: string; target_email_masked: string | null;
  actor_user_id: string; actor_email: string | null; reason: string | null; created_at: string;
}

/** POST /api/chat (backend/app/routers/chat.py, docs/specs/chat-search.md). 문장 하나에 대한 답 */
export interface VesselItem {
  ship_name: string; call_sign: string | null; nationality: string | null; ship_kind: string | null;
  previous_port: string | null; next_port: string | null; purpose: string | null;
  expected_arrival: string | null; facility: string | null;
  /** 부산 출항 예정. 처음 출발한 항구의 출발 시각은 해수부 신고에 없다 */
  planned_departure?: string | null;
  /** 수입 화물선(컨테이너·일반화물·냉동냉장, 양하·양적하). 화면 기본값은 이 배들만 (skills/port-busan/cargo-vessels.md) */
  is_cargo?: boolean;
}
export interface ChatResponse {
  kind: 'cargo' | 'vessels' | 'message'; reply: string;
  agent: AgentResponse | null; request: AgentRequest | null;
  vessels: VesselItem[]; place: string | null; ports: string[]; days: number | null;
}

/** GET /api/vessels/detail (services/vessel_detail.py). 도구가 실패한 칸은 null, 이유는 errors */
export interface VesselDetailResponse {
  call_sign: string | null; ship_name: string | null;
  vessel: {mmsi: number; name: string; flag: string | null; call_sign: string | null; ship_type: number | null} | null;
  position: {lat: number; lng: number; sog: number | null; cog: number | null; navistat: number | null; dest: string | null;
    ais_eta: string | null; last_time: string | null; freshness: Freshness;
    /** 배 → 부산 남은 예상 바닷길 [위도, 경도] (searoute 계산, 실제 항적 아님) */
    route?: [number, number][]} | null;
  distance: {distance_nm: number; calc_hours_at_sog: number | null; calc_eta?: string | null} | null;
  schedule: {planned_arrival: string | null; actual_arrival: string | null; facility: string | null;
    control_events: {kind: string; at: string | null; facility: string | null}[]} | null;
  errors: {source: string; code: string | null; message: string | null}[];
}
