/** Wire contracts transcribed from backend/app/schemas/agent.py (2026-09-28, sale_due_date 선택 입력은 이후 반영).
 * Dates/datetimes serialize as ISO strings. Nullable required fields stay required.
 * Python defaulted fields are optional on request, populated on serialized response.
 * History contracts come from backend/app/routers/history.py, not the mockup.
 */
import type {Citation, EvidenceItem} from './evidenceTypes';  // 답 속 근거 표시
export type Verdict = 'fine' | 'watch' | 'act';
export type Status = 'ok' | 'partial' | 'insufficient' | 'failed' | 'unsupported';
export type VesselMatch = 'confirmed' | 'uncertain' | 'none';
export type Freshness = 'fresh' | 'stale' | 'unknown';
/** 서류 사진에서 확인한 출항일을 /api/chat에 실어 보내는 칸. 서버가 같은 B/L 조회에만 departed_on으로 싣는다 */
export interface ChatDocument { bl_no: string; departed_on: string }
/** 화면에 지금 떠 있는 배들. /api/chat 요청의 선택 칸 on_screen (백엔드 routers/chat.py ChatScreen).
 * 서버는 이 값을 자료로만 LLM에 준다. B/L·컨테이너 번호 칸은 없다. 글자는 80자(시각 40자), 목록은 10줄까지 */
export interface ChatOnScreen {
  vessel?: {ship_name: string; flag?: string | null; mmsi?: number | null; lat?: number | null; lng?: number | null;
    position_time?: string | null; destination?: string | null} | null;
  /** call_sign: 배를 지켜볼 때 서버가 MMSI를 찾는 열쇠. selected: 사용자가 목록에서 고른 줄(지도에 보이는 배) */
  arrivals?: {ship_name: string; flag?: string | null; eta?: string | null; previous_port?: string | null; call_sign?: string | null; selected?: boolean}[];
}
export interface AgentRequest {
  bl_no: string;
  bl_type: 'MASTER' | 'HOUSE';
  // 선택 입력. 없으면 null로 보내고 백엔드는 배 상태만으로 판정한다
  sale_due_date: string | null;
  session_id: string;
  follow_up_question?: string | null;
  resolved_mmsi?: number | null;
  voyage_no?: string | null;
  forwarder_eta?: string | null;
  /** 서류 사진에서 사용자가 확인한 출항일. 내 화물 현황 표 출항 칸에만 쓰이고 판정에는 안 쓰인다. 직접 적은 날짜는 덮지 않는다 */
  departed_on?: string | null;
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
  /** 어디서 어디로 (UNI-PASS 적재항·양륙항). 없으면 null */
  loading_port?: string | null; loading_port_name?: string | null; loading_country?: string | null;
  discharge_port?: string | null; discharge_port_name?: string | null;
  /** UNI-PASS 포워더·선사·컨테이너 번호. 서버가 못 읽으면 없다 */
  forwarder_name?: string | null; carrier_name?: string | null; container_no?: string | null;
  /** 품명 prnm. 적하목록 영어 그대로 (백엔드) */
  goods_name?: string | null;
}
export interface BerthInfo { facility: string | null; shed: string | null }
export interface AgentResponse {
  status: Status; verdict: Verdict | null; vessel_match: VesselMatch;
  vessel_candidates: VesselCandidate[]; missing_inputs: string[]; reasons: Reason[];
  conflicts: Conflict[]; actions: string[]; days_margin: number | null;
  decided_by: 'rule' | 'llm' | null; vessel: VesselInfo | null;
  position: Position | null; eta: EtaInfo | null; customs: CustomsInfo | null;
  berth: BerthInfo | null; evidence: Evidence[]; answer: string; trace_id: string;
  /** UNI-PASS 처리 이력 원문. 화면 전용이라 이력 재생·후속 질문 응답에는 없을 수 있다 (docs/specs/customs-detail.md) */
  customs_detail?: CustomsDetailRow[];
}
export interface HistoryItem {
  request_id: string | null; bl_masked: string | null; status: string | null;
  verdict: string | null; vessel_match: string | null; decided_by: 'rule' | 'llm' | null;
  model: string | null; trace_id: string | null; created_at: string;
  /** 한 줄 이유 (서버가 코드로 만든다). 근거가 되는 값이 없으면 null (M2) */
  reason?: string | null;
}
export interface HistoryResponse { items: HistoryItem[]; available: boolean }

/** POST /api/document 응답. backend/app/schemas/document.py 그대로 (C1~C8 밖의 새 계약). */
export type DocumentCheck = 'missing' | 'not_in_text' | 'format' | 'ambiguous';
export interface DocumentField { value: string | null; checks: DocumentCheck[] }
/** B/L 조건 세 칸·인코텀즈·화물 인도 연락처 (결정 6). 서류에 없으면 value null, checks 빈 목록 */
export type DocumentConditionKey = 'original_bl' | 'to_order_bank' | 'freight_term' | 'incoterm'
  | 'contact_company' | 'contact_role' | 'contact_phone';
export type DocumentFieldKey = 'bl_no' | 'vessel' | 'voyage' | 'eta' | 'pol' | 'pod' | 'item' | DocumentConditionKey;
export interface DocumentResponse {
  status: 'ok' | 'partial';
  needs_review: boolean;
  /** etd(출항일)는 옛 서버 응답에 없을 수 있어 선택이다 */
  fields: Record<DocumentFieldKey, DocumentField> & {etd?: DocumentField};
  ocr: { lines: number; rotation: 0 | 180 | 270; runs: number; ocr_ms: number };
  trace_id: string;
  /** 서류의 MRN (코드가 뽑음). 없으면 null */
  mrn?: string | null;
  /** 서류 종류. 거래처를 기억할 때 출처로 쓴다. 모르면 null */
  doc_kind?: 'B/L' | 'A/N' | null;
  /** AI가 서류 글자를 정리하지 못했을 때 실패 종류(bad_format, timeout 등). 성공이면 null. 옛 서버 응답에는 없다 */
  llm_error?: string | null;
}

/** 화물 비서 기억 (backend/app/schemas/memory.py, docs/specs/memory.md). 원본 B/L은 오지 않는다 */
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
  /** 메모장 글자 수와 상한 (M5). 옛 서버 응답에는 없을 수 있다 */
  used_chars?: number; max_chars?: number;
}
/** POST /api/memory/document-facts. 서류 확인 화면에서 사용자가 확인한 값만 보낸다 (결정 7) */
export interface DocumentFactsRequest {
  bl_no: string; bl_type?: 'MASTER' | 'HOUSE' | null; source?: 'B/L' | 'A/N' | null;
  original_bl?: OriginalBl | null; to_order_bank?: boolean | null; freight_term?: FreightTerm | null; incoterm?: Incoterm | null;
  contact?: {company: string; role: ContactRole; phone: string | null} | null;
}
export interface DocumentFactsResponse {
  conditions_saved: boolean;
  contact: 'saved' | 'unchanged' | 'rejected' | 'skipped' | 'full' | 'conflict';
}

/** 운영자 관리 (backend/app/routers/admin.py, docs/specs/operator-admin.md). */
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
export interface OperatorItem { email: string; granted_by: string; granted_at: string; granted_by_email?: string | null }
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
  /** 이번 턴에 에이전트가 실제로 배의 실시간 위치를 조회했을 때만 값이 있다. 없거나 null이면 말풍선 아래 작은 지도를 그리지 않는다.
   * 옛 응답과 데모 모드에는 이 칸이 없으므로 선택 칸이다 (ChatMiniMap) */
  map?: ChatMap | null;
  /** 한 문장에 B/L이 2~3개일 때만 값이 있다(조회한 화물 한 줄씩). 한 개짜리 답과 옛 응답·데모에는 없거나 빈 목록이다 (ChatCargoTable).
   * agent·request는 첫 줄의 것과 같은 모양이라 줄을 누르면 단일 화물 답처럼 아래 결과 칸을 바꾼다 */
  cargos?: ChatCargo[];
  /** 에이전트가 이 화물을 지켜보자고 제안했을 때만 값이 있다. reason은 코드가 쓴 문장이고 reply 안에도 이미 들어 있다. 옛 응답·데모에는 없거나 null */
  watch_offer?: WatchOffer | null;
  /** 대화로 지켜보기를 방금 켰거나 껐을 때만 값이 있다 ("응", "그만 지켜봐"). 없거나 null이면 바뀐 게 없다 */
  watch_set?: WatchSet | null;
  /** 대화로 배 한 척을 감시 목록에 넣거나 뺐을 때만 값이 있다. 배 지켜보기 버튼이 새로 읽는다 */
  watch_vessel_set?: WatchVesselSet | null;
  /** 답 문장 속 [E1] 표시가 가리키는 근거 묶음과 표시 위치. 서버가 검증을 끝낸 값이다. 옛 응답·데모에는 없거나 빈 목록이다 (EvidencePopover) */
  evidence_items?: EvidenceItem[];
  citations?: Citation[];
}
/** ChatResponse.watch_offer. logged_in은 서버가 본 로그인 여부 */
export interface WatchOffer { bl_no: string; reason: string; logged_in: boolean }
/** ChatResponse.watch_vessel_set */
export interface WatchVesselSet { mmsi: number; name: string; on: boolean }
/** ChatResponse.watch_set */
export interface WatchSet { bl_no: string; on: boolean }
/** ChatResponse.cargos의 한 줄 (백엔드 routers/chat.py ChatCargo). bl_no는 사용자가 입력한 값 그대로 */
export interface ChatCargo {
  bl_no: string; status: string; verdict: 'fine' | 'watch' | 'act' | null; ship_name: string | null;
  eta: string | null; days_margin: number | null; sale_due_date: string | null;
  /** 판정을 못 낸 줄이 필요로 하는 것의 짧은 이유 ("같은 이름 배 2척"). 판정이 났으면 null */
  note: string | null;
  agent: AgentResponse; request: AgentRequest;
}
/** ChatResponse.map. 말풍선 아래 작은 지도 한 점 (백엔드 계약) */
export interface ChatMap { lat: number; lng: number; ship_name: string | null; distance_nm: number | null; received_at: string | null; source: string }
/** POST /api/chat, /api/chat/stream 요청의 history 한 줄. 지금 질문보다 앞선 대화이고 오래된 것부터 둔다.
 * 서버 에이전트가 "그 배", "아까 그거" 같은 말을 풀 때 쓴다. B/L 번호는 서버가 가리므로 화면 글자 그대로 보낸다 */
export interface ChatHistoryTurn { role: 'user' | 'assistant'; text: string }

/* ---------- 대화 목록 (GET/DELETE /api/conversations) ---------- */
/** GET /api/conversations 한 줄. id는 그 대화의 chat session_id와 같다. 새 대화는 새 session_id다 */
export interface ConversationSummary { id: string; title: string; updated_at: string }
/** GET /api/conversations/{id}의 메시지 한 줄. extra는 서버가 저장해 둔 그 턴의 화면용 값(ChatResponse의 kind, vessels, map, cargos, watch_offer, watch_set)이라
 * 말풍선을 처음 답이 왔을 때와 같게 다시 그린다. 사용자 턴과 옛 대화에는 null이다 */
export interface ConversationMessage { role: 'user' | 'assistant'; text: string; created_at: string; extra: Partial<ChatResponse> | null }
/** GET /api/conversations/{id}. context·result는 아래 결과 칸에 되살릴 마지막 화물(단일 화물 답을 받았을 때와 같은 값). 없으면 null */
export interface ConversationDetail { id: string; title: string; messages: ConversationMessage[]; context: AgentRequest | null; result: AgentResponse | null }

/** GET /api/vessels/detail (services/vessel_detail.py). 도구가 실패한 칸은 null, 이유는 errors */
export interface VesselDetailResponse {
  call_sign: string | null; ship_name: string | null;
  /** imo·similarity·source·fetched_at·cached_at는 MCP 도구 응답이 그대로 온다. 없으면 쓰지 않는다. similarity는 선명이 비슷한 정도일 뿐 내 배라는 뜻이 아니다 */
  vessel: {mmsi: number; name: string; flag: string | null; call_sign: string | null; ship_type: number | null;
    imo?: number | null; similarity?: number | null; source?: string | null; fetched_at?: string | null; cached_at?: string | null} | null;
  position: {lat: number; lng: number; sog: number | null; cog: number | null; navistat: number | null; dest: string | null;
    ais_eta: string | null; last_time: string | null; freshness: Freshness;
    /** 배 → 부산 남은 예상 바닷길 [위도, 경도] (searoute 계산, 실제 항적 아님) */
    route?: [number, number][];
    destcode?: string | null; source?: string | null; fetched_at?: string | null; cached_at?: string | null} | null;
  distance: {distance_nm: number; calc_hours_at_sog: number | null; calc_eta?: string | null; source?: string | null; fetched_at?: string | null} | null;
  schedule: {planned_arrival: string | null; actual_arrival: string | null; facility: string | null;
    control_events: {kind: string; at: string | null; facility: string | null}[]; source?: string | null; fetched_at?: string | null} | null;
  errors: {source: string; code: string | null; message: string | null}[];
  /** 이 자세히 보기 결과를 서버가 만든 시각 (10분 캐시 기준) */
  cached_at?: string | null;
}

/** GET /api/kakao/status. configured: 서버에 카카오 설정이 있나, linked: 이 사용자가 연결했나 (backend/app/routers/kakao.py) */
/** linked_at: 연결한 시각, last_sent_at: 마지막으로 보낸 시각(보낸 적 없으면 null). 옛 서버 응답에는 없을 수 있다 (M7) */
export interface KakaoStatus { configured: boolean; linked: boolean; linked_at?: string | null; last_sent_at?: string | null }
/** POST /api/kakao/callback 결과 이름. 주소 ?kakao= 로 설정 화면에 넘길 때도 같은 이름을 쓴다(동의 취소 denied는 화면이 만든다) */
export type KakaoLinkResult = 'connected' | 'expired' | 'mismatch' | 'no_consent' | 'failed';

/** POST /api/cargo/watch/state. saved: 이 화물의 기록이 서버에 저장됐나(조회 직후 비동기로 저장돼 잠깐 false일 수 있다), watch: 지켜보는 중인가 */
export interface WatchState { saved: boolean; watch: boolean }
/** GET /api/watch/changes의 한 줄. 지난 접속 뒤 판정이 바뀐 지켜보는 화물. B/L은 마스킹된 값만 온다 */
export interface WatchChange { bl_masked: string; label: string | null; from_verdict: Verdict; to_verdict: Verdict; changed_at: string;
  /** 서버가 판정이 바뀐 이유를 문장으로 보내 주면 붙인다. 없으면 쓰지 않는다 */
  reason?: string | null }

/** 내 화물 현황 표 (GET /api/cargo/sheet). 날짜는 모두 "YYYY-MM-DD" */
export interface CargoLc { id: number; lc_no: string; opened_on: string | null }
export interface CargoSheetRow {
  cargo_key: string; bl_masked: string; label: string | null; status: 'active' | 'done';
  /** 출항일. 사용자가 적었으면 manual, 도착 통지서에서 읽었으면 document */
  departed_on: string | null; departed_source: 'manual' | 'document' | null;
  /** 입항·입고는 서버가 UNI-PASS에서 채운다. arrived_on이 비었을 때만 eta(입항 예정)를 보인다 */
  arrived_on: string | null; eta: string | null; warehoused_on: string | null; last_stage: string | null;
  forwarder_name: string | null; carrier_name: string | null; container_no: string | null;
  /** 품명(020). 있으면 B/L 아래 굵은 줄로 보이고, 없으면 label로 대신한다 */
  goods_name?: string | null;
  /** 확정된 배의 이름·국적 (021). 새 칸이라 기존 줄은 비어 있을 수 있다 */
  vessel_name?: string | null; vessel_flag?: string | null;
}
/** lc가 null인 묶음은 아직 신용장에 안 묶인 B/L이다 (맨 끝) */
export interface CargoSheetGroup { lc: CargoLc | null; rows: CargoSheetRow[] }
/** truncated: 화물이 500줄을 넘어 앞쪽만 담았다 (S5). 옛 서버는 이 칸이 없다 */
export interface CargoSheet { groups: CargoSheetGroup[]; truncated?: boolean }

/** UNI-PASS 처리 이력 1줄 원문 (backend schemas/customs.py CustomsDetailRow). 값은 UNI-PASS 글자 그대로, 빈 칸은 null */
export interface CustomsDetailRow {
  kind: string | null; processed_at: string | null; declaration_no: string | null; moved_at: string | null;
  basis: string | null; content: string | null; notice: string | null; shed_name: string | null; shed_code: string | null;
  package_count: string | null; package_unit: string | null; weight: string | null; weight_unit: string | null;
}

/** POST /api/document/bl 응답. 채팅 첨부가 쓴다. 코드가 뽑은 B/L·MRN만 있고 LLM 칸은 없다.
 * bl_no가 null이면 서류에서 번호를 못 찾은 것이다 */
export interface DocumentBlResponse { bl_no: string | null; mrn: string | null; ocr: {lines: number; rotation: number; runs: number; ocr_ms: number}; trace_id: string }
