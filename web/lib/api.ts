/** 화면이 백엔드와 주고받는 유일한 통로 (SDD 4.3, 4.4, 5.13).
 *
 * 두 모드가 있다. 빌드할 때 NEXT_PUBLIC_API_BASE가 정해 준다.
 * - 실제 모드(값 있음): POST /api/agent, GET /api/history를 그 주소로 부른다
 * - 데모 모드(값 없음): lib/fixtures의 가공 응답만 쓴다. 키도 서버도 없이 화면 전체를 볼 수 있다
 * 화면 컴포넌트는 어느 모드인지 몰라도 된다. 요청·응답 모양은 backend/app/schemas/agent.py(C1, C2) 그대로다.
 * 서버 API 키는 여기에 두지 않는다. NEXT_PUBLIC_* 값은 브라우저에 그대로 보이기 때문이다 (SDD 7절).
 */
import type { AgentRequest, AgentResponse, CustomersResponse, DocumentFactsRequest, DocumentFactsResponse, DocumentResponse, DocumentBlResponse, HistoryResponse, KakaoLinkResult, KakaoStatus, MemoryResponse, MeResponse, OperatorsResponse, WatchChange, WatchState, ProfileData, UnmaskResponse, ActionItem, ChatResponse, ChatHistoryTurn, ChatDocument, ChatOnScreen, VesselDetailResponse, ConversationSummary, ConversationDetail, CargoSheet, CargoSheetRow } from './types';
import type {Citation, EvidenceItem} from './evidenceTypes';
import {accessToken} from './auth';
import {createSseParser, isStage, type ProgressStage} from './progress';
import ok from './fixtures/ok.json';
import partial from './fixtures/partial.json';
import insufficient from './fixtures/insufficient.json';
import failed from './fixtures/failed.json';
import unsupported from './fixtures/unsupported.json';
import watch from './fixtures/watch.json';
import act from './fixtures/act.json';
import history from './fixtures/history.json';
import demo from './fixtures/demo.json';
import metrics from './fixtures/metrics.json';
import settings from './fixtures/settings.json';
import watchMap from './fixtures/watch-map.json';
import geography from './fixtures/geography.json';
import documentFixture from './fixtures/document.json';
import adminFixture from './fixtures/admin.json';
import memoryFixture from './fixtures/memory.json';

/** 끝 슬래시를 뗀 백엔드 주소. 비어 있으면 데모 모드다. */
/** 정지된 계정에 서버가 403 account_suspended를 줄 때 보여 줄 문장. getMe가 이 문장으로 정지를 알아본다 */
export const SUSPENDED_MESSAGE = '운영자가 이 계정을 일시 정지했어요. 문의가 필요하면 운영자에게 연락해 주세요.';

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? '').trim().replace(/\/+$/, '');
export const isLive = API_BASE !== '';

/** 판정은 LLM 호출과 재시도(validate 3단계, SDD 5.7)까지 기다려야 해서 넉넉히 잡는다. 이력은 DB 읽기뿐이다. */
const AGENT_TIMEOUT_MS = 90_000;
const HISTORY_TIMEOUT_MS = 15_000;
/** 서류 사진은 OCR(1~2초, 누운 사진은 3번)과 소형 LLM 한 번이다 (routers/document.py). */
const DOCUMENT_TIMEOUT_MS = 60_000;
/** routers/document.py MAX_BYTES와 같다. 보내기 전에 막아 큰 파일을 올리느라 기다리지 않게 한다 */
export const DOCUMENT_MAX_BYTES = 10 * 1024 * 1024;

/** 실제 모드의 예시 B/L. 백엔드 REPLAY_MODE 데모와 같다 (scripts/demo/make_demo.py). 앞 10건은 라이브 시연용 모의 화물
 * (scripts/demo/demo_live.py), 뒤 3건은 평가셋 데모 3건이다 (README "키 없이 데모").
 * sale_in_days: 판매 예정일을 "오늘(한국) + N일"로 채운다. 서버 데모는 해수부 입항 예정을 "오늘 + 일"로 못 박아 만들어서
 * (scripts/demo/demo_live.py finalize) 이 날짜를 넣으면 표의 등급과 여유 일수가 나온다. 값은 evals/fixtures/demo_live.jsonl의
 * demo_sale_in_days와 같아야 하고 backend/tests/test_demo_live.py가 맞는지 본다. 없는 예시는 비운다.
 */
export const liveExamples = [
  {id: 'DEMOQD2610001', label: '순항 · 황해 항해 중', bl_no: 'DEMOQD2610001', bl_type: 'HOUSE' as const, sale_in_days: 10},
  {id: 'DEMOSH2610002', label: '주의 · 도착 예정일이 서로 다름', bl_no: 'DEMOSH2610002', bl_type: 'HOUSE' as const, sale_in_days: 8},
  {id: 'DEMONB2610003', label: '긴급 · 도착이 판매 예정일보다 늦음', bl_no: 'DEMONB2610003', bl_type: 'HOUSE' as const, sale_in_days: 2},
  {id: 'DEMOHC2610004', label: '긴급 · 세관 검사 지정', bl_no: 'DEMOHC2610004', bl_type: 'HOUSE' as const},
  {id: 'DEMOTJ2610005', label: '긴급 · 부산 앞 30시간 대기', bl_no: 'DEMOTJ2610005', bl_type: 'HOUSE' as const},
  {id: 'DEMODL2610006', label: '주의 · 10시간 전 위치만 받음', bl_no: 'DEMODL2610006', bl_type: 'HOUSE' as const, sale_in_days: 9},
  {id: 'DEMOKH2610007', label: '주의 · 목적지가 부산이 아님', bl_no: 'DEMOKH2610007', bl_type: 'HOUSE' as const, sale_in_days: 10},
  {id: 'DEMOHP2610008', label: '확인 필요 · 같은 이름 배 2척', bl_no: 'DEMOHP2610008', bl_type: 'HOUSE' as const, sale_in_days: 7},
  {id: 'DEMOSH2610009', label: '순항 · 수입신고 수리', bl_no: 'DEMOSH2610009', bl_type: 'HOUSE' as const},
  {id: 'DEMOQD2610010', label: '반출 완료 · 순항', bl_no: 'DEMOQD2610010', bl_type: 'HOUSE' as const},
  {id: 'TESTBL01', label: '정상 · 순항 (평가용 예시)', bl_no: 'TESTBL01', bl_type: 'HOUSE' as const},
  {id: 'TESTBL04', label: '같은 이름 배 2척 · 확인 필요 (평가용 예시)', bl_no: 'TESTBL04', bl_type: 'HOUSE' as const},
  {id: 'TESTBL26', label: '위치 권한 없음 · 판정 보류 (평가용 예시)', bl_no: 'TESTBL26', bl_type: 'HOUSE' as const},
];

/* ---------- 세션 ID ---------- */

const SESSION_KEY = 'marvia-session-id';
let memorySession = '';
let activeSession = '';

/** 지금 대화의 session_id를 정한다. 빈 값이면 브라우저 값(위 SESSION_KEY)으로 돌아간다 */
export function setActiveSession(id: string): void { activeSession = id; }
/** 새 대화용 session_id. 서버가 이 값으로 대화를 만들어 저장한다 */
export function newSessionId(): string { return crypto.randomUUID(); }

/** 실제 모드에서 이 브라우저를 구분하는 ID. 이력(GET /api/history)이 이 값으로 묶인다.
 * localStorage가 막힌 창(사생활 보호 모드 등)에서는 탭이 열려 있는 동안만 같은 값을 쓴다.
 * 데모 모드는 fixture 이력과 맞도록 demo.json의 고정 세션을 쓴다.
 */
export function currentSessionId(): string {
  if (!isLive) return demo.session_id;
  // 대화 하나가 chat session_id 하나다. 대화를 열거나 새로 시작하면 AppProvider가 이 값을 정한다.
  // 그래서 다음 /api/chat 요청과 Langfuse 세션이 그 대화로 이어진다. 정하지 않았으면 아래의 브라우저 값을 쓴다
  if (activeSession) return activeSession;
  if (typeof window === 'undefined') return '';
  try {
    const saved = window.localStorage.getItem(SESSION_KEY);
    if (saved) return saved;
    const fresh = crypto.randomUUID();
    window.localStorage.setItem(SESSION_KEY, fresh);
    return fresh;
  } catch {
    memorySession ||= crypto.randomUUID();
    return memorySession;
  }
}

/* ---------- 실제 모드 ---------- */

/** FastAPI 오류 본문({detail})을 사람이 읽을 문장으로 바꾼다. 상태 코드는 SDD 8절 표. */
// 422 응답의 칸 이름(C2 요청 필드)을 화면 말로. 모르는 칸은 "입력한 값"으로 쓴다
const FIELD_NAMES: Record<string, string> = {
  bl_no: 'B/L 번호', sale_due_date: '판매 예정일', bl_type: 'B/L 구분', voyage_no: '항차 번호',
  forwarder_eta: '포워더가 알려 준 입항 예정일', follow_up_question: '질문', message: '입력한 문장', resolved_mmsi: '선택한 선박',
};
async function errorMessage(res: Response): Promise<string> {
  let detail = '';
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string') detail = body.detail;
    // 422는 detail이 [{loc, msg}] 목록이다. 첫 칸 이름만 보여 준다
    else if (Array.isArray(body?.detail) && body.detail[0]) detail = `${FIELD_NAMES[String(body.detail[0].loc?.at(-1) ?? '')] ?? '입력한 값'}을(를) 확인해 주세요.`;
  } catch { /* 본문이 JSON이 아니면 상태 코드로만 안내한다 */ }
  if (res.status === 401) return '로그인이 필요해요. 로그인한 뒤 다시 시도해 주세요.';
  if (res.status === 413 || detail === 'too_large') return '사진이 너무 커요. 10MB 이하로 올려 주세요.';
  if (detail === 'invalid_image') return '사진을 읽지 못했어요. JPG·PNG 사진인지 확인해 주세요.';
  if (detail === 'invalid_pdf') return 'PDF를 열지 못했어요. 암호가 걸렸거나 파일이 손상됐는지 확인해 주세요.';
  if (res.status === 503) return detail || '서버에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.';
  if (detail === 'account_suspended') return SUSPENDED_MESSAGE;
  if (res.status === 403) return detail || '운영자만 쓸 수 있어요.';
  if (res.status === 409) return detail || '이미 처리된 요청이에요.';
  if (detail === 'daily_token_limit') return QUOTA_MESSAGE;
  if (res.status === 429) return '요청이 많아요. 잠시 뒤 다시 시도해 주세요.';
  if (res.status === 400 || res.status === 422) return detail || '입력값을 확인해 주세요.';
  return detail || '요청을 처리하지 못했어요. 잠시 뒤 다시 시도해 주세요.';
}

/** 타임아웃을 건 fetch. 연결 자체가 안 되면 주소를 알려 줘서 백엔드가 떠 있는지 확인하게 한다. */
/** 연결 자체가 안 될 때 다시 시도하는 간격. 서버 재시작(몇 초) 중에 보낸 요청이 바로 실패하지 않게 한다 */
const RETRY_DELAYS_MS = [1500, 3000];

/** fetch 한 번. 연결 실패(TypeError)는 그대로 올려 call이 다시 시도하게 한다. */
async function callOnce(path: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    // 로그인했으면 출입증을 붙인다 (backend/app/auth.py). 로그인이 꺼져 있으면 헤더 없이 간다
    const token = await accessToken();
    const headers = new Headers(init.headers);
    if (token) headers.set('authorization', `Bearer ${token}`);
    const res = await fetch(`${API_BASE}${path}`, {...init, headers, signal: controller.signal});
    if (!res.ok) throw Object.assign(new Error(await errorMessage(res)), {status: res.status});  // 대화 목록이 401/503/404를 가르려고 상태 코드를 붙인다
    return res;
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw new Error('답이 너무 늦어져 중단했어요. 다시 시도해 주세요.');
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

/** 타임아웃과 재시도를 건 fetch.
 * 연결 자체가 안 되면(서버 재시작·잠깐 끊김) 1.5초, 3초 뒤 두 번 더 해 본다. 응답이 온 오류(4xx·5xx)는 다시 하지 않는다.
 * 연결 실패는 응답이 없으니 서버가 요청을 처리하지 않은 것이라, 다시 보내도 같은 일이 두 번 되지 않는다. */
async function call(path: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await callOnce(path, init, timeoutMs);
    } catch (e) {
      if (!(e instanceof TypeError)) throw e;
      if (attempt >= RETRY_DELAYS_MS.length) {
        throw new Error('서버에 연결하지 못했어요. 인터넷 연결을 확인하고 잠시 뒤 다시 시도해 주세요.');
      }
      await new Promise(r => setTimeout(r, RETRY_DELAYS_MS[attempt]));
    }
  }
}

/** C2에 있는 칸만, 빈 값은 null로 보낸다. 빈 문자열 날짜는 백엔드에서 422가 되기 때문이다. */
function wireRequest(req: AgentRequest): AgentRequest {
  const text = (v: string | null | undefined) => (v && v.trim() ? v.trim() : null);
  return {
    bl_no: req.bl_no.replace(/\s/g, '').toUpperCase(),
    bl_type: req.bl_type,
    sale_due_date: text(req.sale_due_date),
    session_id: currentSessionId(),
    follow_up_question: text(req.follow_up_question),
    resolved_mmsi: req.resolved_mmsi ?? null,
    voyage_no: text(req.voyage_no),
    forwarder_eta: text(req.forwarder_eta),
  };
}

async function liveAgentResponse(req: AgentRequest): Promise<AgentResponse> {
  const res = await call('/api/agent', {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify(wireRequest(req)),
  }, AGENT_TIMEOUT_MS);
  return res.json();
}

/** call이 던진 오류의 HTTP 상태 코드. 연결 실패 같은 응답 없는 오류는 undefined */
export function errorStatus(e: unknown): number | undefined {
  const s = (e as {status?: unknown} | null)?.status;
  return typeof s === 'number' ? s : undefined;
}

/* ---------- 대화 목록 ---------- */
// 로그인해야 쓸 수 있다(401). DB가 없으면 503. 호출하는 쪽이 이 둘을 "목록 없음"으로 본다. 데모 모드에는 저장된 대화가 없다.

/** GET /api/conversations. 최근 순, 서버가 최대 50개까지 준다 */
export async function listConversations(): Promise<ConversationSummary[]> {
  if (!isLive) return [];
  return ((await (await call('/api/conversations', {}, HISTORY_TIMEOUT_MS)).json()).conversations ?? []) as ConversationSummary[];
}

/** GET /api/conversations/{id}. 없으면 404 */
export async function getConversation(id: string): Promise<ConversationDetail> {
  if (!isLive) throw new Error('체험 모드에는 저장된 대화가 없어요.');
  return (await call(`/api/conversations/${encodeURIComponent(id)}`, {}, HISTORY_TIMEOUT_MS)).json();
}

/** DELETE /api/conversations/{id} */
export async function deleteConversation(id: string): Promise<{deleted: boolean}> {
  if (!isLive) throw new Error('체험 모드에는 지울 대화가 없어요.');
  return liveDelete(`/api/conversations/${encodeURIComponent(id)}`);
}

/** 이력은 부가 기능이다. 못 읽으면 화면을 죽이지 않고 available:false로 돌려준다 (routers/history.py와 같은 원칙). */
async function liveHistory(since?: string): Promise<HistoryResponse> {
  try {
    const res = await call(`/api/history?session_id=${encodeURIComponent(currentSessionId())}${since ? `&since=${encodeURIComponent(since)}` : ''}`, {}, HISTORY_TIMEOUT_MS);
    return await res.json();
  } catch {
    return {items: [], available: false};
  }
}

/** 서류 사진 한 장을 보내 7칸을 받는다. 판정으로 바로 넘기지 않는다. 사용자가 확인한 값만 조회에 쓴다 (docs/specs/document-extract.md). */
async function liveDocument(file: File): Promise<DocumentResponse> {
  const form = new FormData();
  form.append('file', file);
  form.append('session_id', currentSessionId());
  const res = await call('/api/document', {method: 'POST', body: form}, DOCUMENT_TIMEOUT_MS);
  return res.json();
}

/** 서류에서 B/L(과 MRN)만 코드로 뽑는다 (POST /api/document/bl). LLM을 안 부르므로 빠르다 */
async function liveDocumentBl(file: File): Promise<DocumentBlResponse> {
  const form = new FormData();
  form.append('file', file);
  form.append('session_id', currentSessionId());
  const res = await call('/api/document/bl', {method: 'POST', body: form}, DOCUMENT_TIMEOUT_MS);
  return res.json();
}

/** 이력 삭제·탈퇴는 실패를 숨기지 않는다. 지운 줄 알았는데 남아 있으면 안 되므로 오류를 그대로 올린다 (routers/history.py). */
async function liveDelete<T>(path: string): Promise<T> {
  const res = await call(path, {method: 'DELETE'}, HISTORY_TIMEOUT_MS);
  return res.json();
}

/* ---------- 데모 모드 (fixture) ---------- */

const responses: Record<string, AgentResponse> = {ok, partial, insufficient, failed, unsupported, watch, act} as Record<string, AgentResponse>;
let selectedFixture: string | null = null;
let previous: { key: string; response: AgentResponse } | null = null;
const pause = () => new Promise<void>(resolve => setTimeout(resolve, 1050));

/** 저장된 예시 B/L을 그 예시의 조건 그대로만 재생한다. 새 입력에 맞춰 판정을 지어내지 않는다 (SDD 5.13 데모 모드). */
async function demoAgentResponse(req: AgentRequest): Promise<AgentResponse> {
  await pause();
  const normalized = req.bl_no.replace(/\s/g, '').toUpperCase();
  if (!/^[A-Z0-9]{8,20}$/.test(normalized)) throw new Error('B/L은 영문·숫자 8~20자로 입력해 주세요.');
  if ((req.follow_up_question?.length ?? 0) > 300) throw new Error('질문은 300자 이내로 입력해 주세요.');
  const key = `${req.session_id}:${normalized}`;
  const choice = demo.choices.find(c => c.request.bl_no === normalized);
  if (choice && ((req.sale_due_date ?? null) !== choice.request.sale_due_date || req.bl_type !== choice.request.bl_type)) {
    throw new Error('저장된 예시와 조회 조건이 달라요. 예시 화물을 다시 선택하면 저장된 판매 예정일·B/L 구분으로 돌아가요.');
  }
  const id = selectedFixture ?? choice?.id;
  if (!id || !responses[id]) throw new Error('저장된 예시 B/L이 없어요. 위에서 예시 화물을 선택해 주세요.');
  let result = structuredClone(responses[id]);
  // 되묻기 해소를 한 가지로만 흉내 낸다. 실제 식별 알고리즘이 아니다
  if (id === 'insufficient' && (req.resolved_mmsi === insufficient.vessel_candidates[0].mmsi || (!req.resolved_mmsi && (req.voyage_no?.trim() || req.forwarder_eta)))) {
    result = structuredClone(responses.ok);
  }
  if (req.follow_up_question) {
    result = structuredClone(previous?.key === key ? previous.response : result);
    result.answer = demo.follow_up_answer;
  }
  previous = {key, response: structuredClone(result)};
  return result;
}

async function demoHistory(sessionId: string): Promise<HistoryResponse> {
  await new Promise<void>(resolve => setTimeout(resolve, 180));
  return sessionId === demo.session_id ? structuredClone(history) as HistoryResponse : {items: [], available: true};
}

/** 데모: 사진 내용과 상관없이 저장된 가공 추출 결과를 돌려준다. 화면에 가공 예시임을 표시한다. */
async function demoDocument(): Promise<DocumentResponse> {
  await pause();
  return structuredClone(documentFixture) as DocumentResponse;
}

/** 데모 전용 모의 근거. 첫 문장 끝(마침표 앞)에 [E1][E2]를 붙여(한 칩으로 합쳐지는 모습) 모의 근거 두 개를 돌려준다.
 * 값은 모두 가공한 모의값이다(CLAUDE.md: 가공 fixture). 정상(ok) 답이고 문장이 둘 이상일 때만 붙인다 */
function demoEvidence(answer: string, status: string): {reply: string; evidence_items?: EvidenceItem[]; citations?: Citation[]} {
  const sentences = answer.match(/[^.]+\./g);
  if (status !== 'ok' || !sentences || sentences.length < 2) return {reply: answer};
  const marked = sentences.map((s, i) => i === 0 ? `${s.slice(0, -1)} [E1][E2].` : s);
  const reply = marked.join('') + answer.slice(sentences.join('').length);
  const citations: Citation[] = []; const re = /\[(E\d+)\]/g; let m: RegExpExecArray | null;
  while ((m = re.exec(reply))) citations.push({id: `c${citations.length + 1}`, start: m.index, end: m.index + m[0].length, evidence_ref: m[1]});
  const at = '2026-10-20T09:30:00+09:00';
  return {reply, citations, evidence_items: [
    {id: 'E1', source: 'mof', fetched_at: at, values: [{field: 'mof_planned', value: '2026-10-21 (모의값)'}]},
    {id: 'E2', source: 'rule', fetched_at: at, values: [{field: 'days_margin', value: '4 (모의값)'}]}]};
}

/** 데모: LLM 없이 문장 속 예시 B/L만 알아본다. 배 검색은 가공 예시 표 (실제 모드에서는 서버가 LLM으로 처리) */
async function demoChat(message: string, context: AgentRequest | null): Promise<ChatResponse> {
  const empty = {agent: null, request: null, vessels: [], place: null, ports: [], days: null};
  const bl = message.toUpperCase().match(/MRVDEMO\d{4}/)?.[0];
  const choice = bl ? demo.choices.find(c => c.request.bl_no === bl) : undefined;
  if (choice) {
    const request = choice.request as AgentRequest;
    const agent = await demoAgentResponse(request);
    // 데모에서도 작은 지도가 보이게, 위치가 있는 예시 화물은 그 위치를 map으로 함께 돌려준다 (실제 모드는 서버가 채운다)
    const pos = agent.position;
    const map = pos ? {lat: pos.lat, lng: pos.lng, ship_name: agent.vessel?.name ?? null, distance_nm: agent.eta?.distance_nm ?? null, received_at: pos.last_time, source: 'shipfinder'} : null;
    // 데모에서도 답 속 근거 표시가 보이게 정상 답에는 모의 근거를 붙인다 (모의값. 실제 모드는 서버가 채운다)
    return {...empty, kind: 'cargo', ...demoEvidence(agent.answer, agent.status), agent, request, map};
  }
  // 화물을 보고 있을 때 "배 지금 어디쯤이야?"처럼 그 화물의 배를 묻는 문장은 후속 질문이다. 선박 검색은 지역·목록을 찾는
  // 문장 모양일 때만 고른다 (UI 점검 F6). 실제 모드는 서버 LLM이 의도를 고르므로 이 규칙은 데모에만 있다
  const searchLike = /(들어오는|들어올|오는|입항하는|입항할|입항 예정)\s*(배|선박)|(배|선박)\s*(보여|알려|목록|전부|있어|찾아)|중국|일본|베트남|상하이|싱가포르|대만|홍콩|태국/.test(message);
  if (/배|선박|입항/.test(message) && (!context || searchLike)) {
    await pause();
    return {...empty, kind: 'vessels', ...structuredClone(demo.vessel_search), reply: demo.vessel_search.reply} as ChatResponse;
  }
  if (context) {
    const agent = await demoAgentResponse({...context, follow_up_question: message.slice(0, 300)});
    return {...empty, kind: 'cargo', reply: agent.answer, agent, request: context};
  }
  await pause();
  return {...empty, kind: 'message', reply: '체험 모드에서는 예시 B/L(MRVDEMO1101~1107)이 든 문장이나 "중국에서 오는 배"처럼 물어볼 수 있어요.'};
}

/* ---------- 화면이 쓰는 함수 ---------- */

/** POST /api/agent. 첫 조회, 되묻기 답, 후속 질문이 모두 이 하나로 간다 (SDD 4.3). */
export async function getAgentResponse(req: AgentRequest): Promise<AgentResponse> {
  return isLive ? liveAgentResponse(req) : demoAgentResponse(req);
}

/** POST /api/chat. 문장 하나로 화물 조회·후속 질문·입항 선박 검색. context는 지금 보고 있는 화물(서버 안에서만 쓴다).
 * history는 지금 질문보다 앞선 대화다. 데모 모드는 저장된 예시만 돌려주므로 쓰지 않는다 */
export async function sendChat(message: string, context: AgentRequest | null, history: ChatHistoryTurn[] = [], document: ChatDocument | null = null, onScreen: ChatOnScreen | null = null): Promise<ChatResponse> {
  if (!isLive) return demoChat(message, context);
  const res = await call('/api/chat', {method: 'POST', headers: {'content-type': 'application/json'},
    body: chatBody(message, context, history, document, onScreen)}, AGENT_TIMEOUT_MS);
  return res.json();
}

/** 서버에 보내는 앞선 대화의 상한. 최근 6줄, 한 줄 500자까지만 보낸다 (에이전트가 맥락을 잇는 데 필요한 만큼만, 요청 크기와 LLM 비용을 묶는다) */
const HISTORY_MAX_TURNS = 6;
const HISTORY_MAX_CHARS = 500;

/** 긴 줄은 앞과 끝을 함께 남긴다. 지켜보기 제안("이 화물을 지켜볼까요?")은 답 끝에 붙는데 앞에서만 자르면 잘려 나가서,
 * 다음 턴의 "응"을 서버가 제안에 대한 대답으로 알아보지 못한다. 띄어쓰기 자리에서만 잘라 B/L 번호가 반쯤 남지 않게 한다
 * (반쪽 번호는 B/L 모양이 아니라 서버가 가리지 못한다) */
function clip(text: string): string {
  if (text.length <= HISTORY_MAX_CHARS) return text;
  const half = Math.floor((HISTORY_MAX_CHARS - 3) / 2);
  const head = text.slice(0, half), tail = text.slice(-half);
  const cutHead = head.lastIndexOf(' ') > 0 ? head.slice(0, head.lastIndexOf(' ')) : '';
  const cutTail = tail.indexOf(' ') >= 0 ? tail.slice(tail.indexOf(' ') + 1) : '';
  return `${cutHead} … ${cutTail}`;
}

/** /api/chat과 /api/chat/stream이 같이 쓰는 본문. 화물은 서버에 필요한 칸만 보낸다.
 * history는 오래된 것부터 두고, role과 text만 남긴다(화면용 kind는 보내지 않는다). B/L 번호는 서버가 가린다 */
function chatBody(message: string, context: AgentRequest | null, history: ChatHistoryTurn[] = [], document: ChatDocument | null = null, onScreen: ChatOnScreen | null = null): string {
  const ctx = context ? {bl_no: context.bl_no, bl_type: context.bl_type, sale_due_date: context.sale_due_date ?? null, mrn: context.mrn ?? null} : null;
  const turns = history.slice(-HISTORY_MAX_TURNS).map(t => ({role: t.role, text: clip(t.text)}));
  return JSON.stringify({message, session_id: currentSessionId(), context: ctx, history: turns, document, on_screen: onScreen});
}

/** 스트림 통로를 못 쓰는 경우의 표시. 서버가 요청을 받지 않은 것이 확실할 때만 쓴다 (chat-progress.md EC-05) */
class StreamUnavailable extends Error {}

/** POST /api/chat/stream. /api/chat과 같은 답을 주면서, 서버가 실제로 들어간 단계를 onStage로 알려 준다 (docs/specs/chat-progress.md).
 * - 새 통로가 없는 서버(404·405)나 응답 전 연결 실패면 /api/chat으로 한 번 대신 보낸다 (EC-05). 이때 단계 소식은 없다
 * - 응답을 받기 시작한 뒤 끊기면 다시 보내지 않는다. 서버는 이미 유료 호출을 하고 있을 수 있다 (EC-06)
 * - 데모 모드는 서버가 없어 단계 소식도 없다. 단계를 지어내지 않는다 (EC-07) */
export async function sendChatStream(message: string, context: AgentRequest | null,
  onStage: (stage: ProgressStage) => void, history: ChatHistoryTurn[] = [], document: ChatDocument | null = null, onScreen: ChatOnScreen | null = null): Promise<ChatResponse> {
  if (!isLive) return demoChat(message, context);
  try {
    return await liveChatStream(message, context, onStage, history, document, onScreen);
  } catch (e) {
    if (e instanceof StreamUnavailable) return sendChat(message, context, history, document, onScreen);
    throw e;
  }
}

async function liveChatStream(message: string, context: AgentRequest | null,
  onStage: (stage: ProgressStage) => void, history: ChatHistoryTurn[] = [], document: ChatDocument | null = null, onScreen: ChatOnScreen | null = null): Promise<ChatResponse> {
  const controller = new AbortController();
  // 전체 시간 제한은 /api/chat과 같다. 판정 LLM 재시도까지 기다린다
  const timer = setTimeout(() => controller.abort(), AGENT_TIMEOUT_MS);
  const timeout = '답이 너무 늦어져 중단했어요. 다시 시도해 주세요.';
  try {
    let res: Response;
    try {
      const token = await accessToken();
      const headers = new Headers({'content-type': 'application/json', accept: 'text/event-stream'});
      if (token) headers.set('authorization', `Bearer ${token}`);
      res = await fetch(`${API_BASE}/api/chat/stream`, {method: 'POST', headers, body: chatBody(message, context, history, document, onScreen), signal: controller.signal});
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') throw new Error(timeout);
      if (e instanceof TypeError) throw new StreamUnavailable();  // 응답이 없었다. /api/chat이 재시도까지 맡는다
      throw e;
    }
    if (res.status === 404 || res.status === 405) throw new StreamUnavailable();
    if (!res.ok) throw new Error(await errorMessage(res));  // 로그인·권한·입력 오류는 스트림을 열기 전에 온다
    if (!res.body) throw new Error('이 브라우저에서 답을 읽지 못했어요. 다시 시도해 주세요.');
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    const parse = createSseParser();
    for (;;) {
      let chunk: ReadableStreamReadResult<string>;
      try { chunk = await reader.read(); }
      catch (e) {
        if (e instanceof DOMException && e.name === 'AbortError') throw new Error(timeout);
        throw new Error('답을 받는 중 연결이 끊겼어요. 다시 물어봐 주세요.');
      }
      if (chunk.done) break;
      for (const ev of parse(chunk.value)) {
        const data = JSON.parse(ev.data);
        if (ev.event === 'progress' && isStage(data?.stage)) onStage(data.stage);
        else if (ev.event === 'result') { void reader.cancel(); return data as ChatResponse; }
        else if (ev.event === 'error') throw new Error(typeof data?.detail === 'string' ? data.detail : '답을 만들지 못했어요. 다시 시도해 주세요.');
      }
    }
    throw new Error('답을 받기 전에 연결이 끊겼어요. 다시 물어봐 주세요.');
  } finally {
    clearTimeout(timer);
  }
}

/** 하루 토큰 한도를 다 썼을 때 안내 (서버 429 daily_token_limit, docs/specs/token-quota.md) */
export const QUOTA_MESSAGE = '오늘 쓸 수 있는 AI 사용량을 모두 썼어요. 내일(한국 시간 자정 이후) 다시 이용해 주세요.';
export interface UsageInfo { limit: number | null; used: number; remaining: number | null; exhausted: boolean; near_limit: boolean }
/** GET /api/usage. 오늘 LLM 토큰 사용량. 데모 모드와 옛 서버(404)는 한도 없음으로 본다. 못 읽으면 막지 않는다 */
export async function getUsage(): Promise<UsageInfo> {
  const none: UsageInfo = {limit: null, used: 0, remaining: null, exhausted: false, near_limit: false};
  if (!isLive) return none;
  try {
    const res = await call(`/api/usage?session_id=${encodeURIComponent(currentSessionId())}`, {}, HISTORY_TIMEOUT_MS);
    return res.ok ? await res.json() as UsageInfo : none;
  } catch { return none; }
}

/** GET /api/vessels/detail. 선박 표에서 선명을 눌렀을 때. 데모 모드는 가공 예시 */
export async function getVesselDetail(callSign: string | null, shipName: string): Promise<VesselDetailResponse> {
  if (!isLive) {
    await pause();
    const now = new Date().toISOString();
    return {call_sign: callSign, ship_name: shipName, vessel: {mmsi: 990000001, name: shipName, flag: 'Panama', call_sign: callSign, ship_type: 70,
        imo: 9990001, similarity: 0.92, source: 'shipfinder', fetched_at: now, cached_at: null},
      position: {lat: 33.2, lng: 127.6, sog: 13.5, cog: 82, navistat: 0, dest: 'KRPUS', destcode: 'KRPUS', ais_eta: null, last_time: now, freshness: 'fresh',
        source: 'shipfinder', fetched_at: now, cached_at: null},
      distance: {distance_nm: 140, calc_hours_at_sog: 10.4, calc_eta: null, source: 'searoute', fetched_at: now}, schedule: null, cached_at: now,
      errors: [{source: 'mof', code: 'demo', message: '예시라서 해수부 일정은 없어요'}]};
  }
  const q = new URLSearchParams({ship_name: shipName, ...(callSign ? {call_sign: callSign} : {})});
  return (await call(`/api/vessels/detail?${q}`, {}, AGENT_TIMEOUT_MS)).json();
}

/** GET /api/history. available:false(못 읽음)와 빈 목록을 구분한다. */
export async function getHistory(sessionId: string = currentSessionId(), since?: string): Promise<HistoryResponse> {
  return isLive ? liveHistory(since) : demoHistory(sessionId);
}

/** POST /api/document. 서류 사진·PDF에서 조회 값 후보를 읽는다. 크기는 보내기 전에 먼저 본다. */
export async function readDocument(file: File): Promise<DocumentResponse> {
  if (file.size > DOCUMENT_MAX_BYTES) throw new Error('사진이 너무 커요. 10MB 이하로 올려 주세요.');
  if (file.type && !file.type.startsWith('image/') && file.type !== 'application/pdf') throw new Error('사진(JPG·PNG)이나 PDF만 올릴 수 있어요.');
  return isLive ? liveDocument(file) : demoDocument();
}

/** 채팅 첨부 보내기: 서류에서 B/L(과 MRN)만 읽는다. 데모 모드는 사진과 상관없이 가공 데모 B/L을 돌려준다 (fixture, 모의값). */
export async function readDocumentBl(file: File): Promise<DocumentBlResponse> {
  if (file.size > DOCUMENT_MAX_BYTES) throw new Error('사진이 너무 커요. 10MB 이하로 올려 주세요.');
  if (file.type && !file.type.startsWith('image/') && file.type !== 'application/pdf') throw new Error('사진(JPG·PNG)이나 PDF만 올릴 수 있어요.');
  if (isLive) return liveDocumentBl(file);
  const r = await demoDocument();
  return {bl_no: r.fields.bl_no.value, mrn: r.mrn ?? null, ocr: r.ocr, trace_id: r.trace_id};
}

/** DELETE /api/history. 로그인한 사용자의 조회 기록을 전부 지운다. 데모 모드에는 지울 실제 기록이 없다. */
export async function deleteMyHistory(): Promise<{deleted: number}> {
  if (!isLive) throw new Error('체험 모드에는 지울 실제 이력이 없어요.');
  return liveDelete('/api/history');
}

/** DELETE /api/account. 기록과 계정을 지운다. 실패하면 503이고 다시 누르면 이어서 끝난다 (services/account.py). */
export async function deleteMyAccount(): Promise<{deleted_records: number; account_deleted: boolean}> {
  if (!isLive) throw new Error('체험 모드에는 탈퇴할 계정이 없어요.');
  return liveDelete('/api/account');
}

/* ---------- 화물 비서 기억 (docs/specs/memory.md, backend/app/routers/memory.py) ---------- */

/** GET /api/memory. 로그인 사용자의 메모장(번호 없는 글 + 항목)과 기억한 화물 요약. 원본 B/L은 오지 않는다.
 * 데모 모드는 가공 예시를 돌려준다(화면에 가공 예시라고 표시). 못 읽으면 오류를 올린다(화면이 안내). */
export async function getMemory(): Promise<MemoryResponse> {
  if (!isLive) { await new Promise<void>(resolve => setTimeout(resolve, 180)); return structuredClone(memoryFixture) as unknown as MemoryResponse; }
  return (await call('/api/memory', {}, HISTORY_TIMEOUT_MS)).json();
}

/** DELETE /api/memory. 메모장과 기억한 화물을 모두 지운다. 실패를 숨기지 않는다(503). 데모 모드에는 지울 실제 기억이 없다. */
export async function deleteAllMemory(): Promise<{deleted: number}> {
  if (!isLive) throw new Error('체험 모드에는 지울 실제 기억이 없어요.');
  return liveDelete('/api/memory');
}

/** DELETE /api/memory/items/{id}. 메모 한 줄을 지운다. */
export async function deleteMemoryItem(id: string): Promise<{deleted: number}> {
  if (!isLive) throw new Error('체험 모드에는 지울 실제 기억이 없어요.');
  return liveDelete(`/api/memory/items/${encodeURIComponent(id)}`);
}

/** POST /api/memory/document-facts. 서류 확인 화면에서 "확인한 값으로 채우기"를 눌렀을 때만 부른다 (결정 7).
 * 실제 모드 + 로그인 사용자일 때만 보낸다. 아니면 아무것도 하지 않고 null. 부르는 쪽은 실패해도 입력 채우기를 막지 않는다. */
export async function saveDocumentFacts(facts: DocumentFactsRequest): Promise<DocumentFactsResponse | null> {
  if (!isLive || !(await accessToken())) return null;
  const res = await call('/api/memory/document-facts', {method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify(facts)}, HISTORY_TIMEOUT_MS);
  return res.json();
}

/* ---------- 카카오톡 "나에게 보내기" 알림 (결정, backend/app/routers/kakao.py) ---------- */

/** GET /api/kakao/status. 연결 버튼을 보여 줄지 정한다. 데모 모드에는 연결할 실제 카카오톡이 없다. */
export async function getKakaoStatus(): Promise<KakaoStatus> {
  if (!isLive) throw new Error('체험 모드에는 연결할 실제 카카오톡이 없어요.');
  return (await call('/api/kakao/status', {}, HISTORY_TIMEOUT_MS)).json();
}

/** POST /api/kakao/connect. 카카오 동의 화면 주소를 받는다. 부르는 쪽이 그 주소로 브라우저를 보낸다. */
export async function connectKakao(): Promise<{url: string}> {
  if (!isLive) throw new Error('체험 모드에는 연결할 실제 카카오톡이 없어요.');
  return (await call('/api/kakao/connect', {method: 'POST'}, HISTORY_TIMEOUT_MS)).json();
}

/** POST /api/kakao/callback. 카카오가 돌려 보낸 code·state를 서버에 넘겨 연결을 마무리한다 (/settings/kakao 화면만 부른다).
 * 로그인 출입증이 붙어서, 서버가 "연결을 시작한 사람 = 지금 로그인한 사람"인지 확인한다. code는 한 번만 쓸 수 있어 다시 보내지 않는다. */
export async function finishKakaoLink(code: string, state: string): Promise<KakaoLinkResult> {
  if (!isLive) throw new Error('체험 모드에는 연결할 실제 카카오톡이 없어요.');
  const res = await call('/api/kakao/callback', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({code, state})}, HISTORY_TIMEOUT_MS);
  return (await res.json()).result;
}

/** POST /api/kakao/test. 시험 메시지를 한 통 보낸다. 실패하면 서버 안내 문장이 그대로 올라온다. 자동으로 다시 보내지 않는다. */
export async function sendKakaoTest(): Promise<{sent: boolean}> {
  if (!isLive) throw new Error('체험 모드에는 연결할 실제 카카오톡이 없어요.');
  return (await call('/api/kakao/test', {method: 'POST'}, HISTORY_TIMEOUT_MS)).json();
}

/** DELETE /api/kakao/link. 연결을 끊고 서버에 둔 토큰을 지운다. */
export async function unlinkKakao(): Promise<{linked: boolean}> {
  if (!isLive) throw new Error('체험 모드에는 연결할 실제 카카오톡이 없어요.');
  return liveDelete('/api/kakao/link');
}

/* ---------- 화물 지켜보기 (G5 작업 리스트, 백엔드 routers의 watch) ---------- */

/** B/L은 URL에 넣지 않는다(서버·프록시 로그에 남는다). 본문 JSON으로만 보낸다. 조회 때와 같게 공백 제거·대문자로 맞춘다 */
export const watchKey = (blNo: string) => blNo.replace(/\s/g, '').toUpperCase();
const watchBody = (blNo: string) => ({bl_no: watchKey(blNo)});

/** POST /api/cargo/watch/state. 이 화물이 저장됐는지, 지켜보는 중인지. 데모 모드에는 계정이 없어 지켜볼 수 없다. */
export async function getWatchState(blNo: string): Promise<WatchState> {
  if (!isLive) throw new Error('체험 모드에서는 화물을 지켜볼 수 없어요.');
  const res = await call('/api/cargo/watch/state', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(watchBody(blNo))}, HISTORY_TIMEOUT_MS);
  return res.json();
}

/** PUT /api/cargo/watch. 지켜보기를 켜거나 끈다. 실패하면 서버 안내 문장이 그대로 올라온다(404 아직 저장 전, 409 끝난 화물·5건 한도, 503). */
export async function setWatch(blNo: string, on: boolean): Promise<{watch: boolean}> {
  if (!isLive) throw new Error('체험 모드에서는 화물을 지켜볼 수 없어요.');
  const res = await call('/api/cargo/watch', {method: 'PUT', headers: {'content-type': 'application/json'}, body: JSON.stringify({...watchBody(blNo), on})}, HISTORY_TIMEOUT_MS);
  return res.json();
}

/** GET /api/watch/changes. 지난 접속 뒤 판정이 바뀐 화물 목록. 데모 모드에는 지켜보는 화물이 없어 빈 목록이다. */
export async function getWatchChanges(): Promise<WatchChange[]> {
  if (!isLive) return [];
  const res = await call('/api/watch/changes', {}, HISTORY_TIMEOUT_MS);
  return (await res.json()).changes ?? [];
}

/** POST /api/watch/changes/seen. 보여 준 변경을 확인 처리한다. 다시 접속해도 같은 알림이 뜨지 않는다. */
export async function markWatchChangesSeen(): Promise<{cleared: number}> {
  if (!isLive) return {cleared: 0};
  return (await call('/api/watch/changes/seen', {method: 'POST'}, HISTORY_TIMEOUT_MS)).json();
}

/* ---------- 내 화물 현황 표 ---------- */

/** 데모 모드의 가짜 표. 값은 전부 지어낸 것이다(MRVDEMO B/L, DEMO 신용장). 실제 번호를 쓰지 않는다 (CLAUDE.md) */
const demoRow = (n: number, extra: Partial<CargoSheetRow>): CargoSheetRow => ({
  cargo_key: `demo-${n}`, bl_masked: `MRVD***${String(n).padStart(4, '0')}`, label: null, status: 'active',
  departed_on: null, departed_source: null, arrived_on: null, eta: null, warehoused_on: null, last_stage: null,
  forwarder_name: null, carrier_name: null, container_no: null, ...extra,
});
let demoSheet: CargoSheet = {truncated: false, groups: [
  {lc: {id: 1, lc_no: 'DEMO-LC-0001', opened_on: '2026-08-20'}, rows: [
    demoRow(1, {status: 'done', departed_on: '2026-09-02', departed_source: 'manual', arrived_on: '2026-09-18', warehoused_on: '2026-09-22', last_stage: '반출', forwarder_name: '데모포워딩', carrier_name: '데모선사', container_no: 'DEMO1234567', goods_name: '건조 고추', vessel_name: 'DEMO TRADER', vessel_flag: 'PA'}),
    demoRow(2, {departed_on: '2026-09-20', departed_source: 'document', arrived_on: '2026-10-03', last_stage: '입항 후 하선', forwarder_name: '데모포워딩', carrier_name: '데모선사', container_no: 'DEMO7654321', goods_name: '냉동 오징어', vessel_name: 'DEMO HARMONY', vessel_flag: 'LR'}),
  ]},
  {lc: {id: 2, lc_no: 'DEMO-LC-0002', opened_on: '2026-09-10'}, rows: [
    demoRow(3, {departed_on: '2026-10-01', departed_source: 'manual', eta: '2026-10-20', last_stage: '선적', carrier_name: '데모선사', goods_name: '참깨', vessel_name: 'DEMO STAR', vessel_flag: 'KR'}),
  ]},
  {lc: null, rows: [demoRow(4, {})]},
]};

/** 데모 모드의 출항일 수정. 새로고침하면 처음 모양으로 돌아간다 */
function demoSetDeparted(cargoKey: string, departedOn: string | null, source: 'manual' | 'document' = 'manual'): CargoSheet {
  const row = demoSheet.groups.flatMap(g => g.rows).find(r => r.cargo_key === cargoKey);
  if (!row) throw Object.assign(new Error('이 화물을 표에서 찾지 못했어요.'), {status: 404});
  row.departed_on = departedOn;
  row.departed_source = departedOn ? source : null;
  return structuredClone(demoSheet);
}

/** 데모 모드의 L/C 묶기. 서버가 하는 일(같은 번호면 같은 묶음, 빈 묶음 정리, 미연결 묶음은 맨 끝)을 흉내 낸다 */
function demoSetLc(cargoKey: string, lcNo: string | null, openedOn: string | null): CargoSheet {
  const from = demoSheet.groups.find(g => g.rows.some(r => r.cargo_key === cargoKey));
  const row = from?.rows.find(r => r.cargo_key === cargoKey);
  if (!from || !row) throw Object.assign(new Error('이 화물을 표에서 찾지 못했어요.'), {status: 404});
  from.rows = from.rows.filter(r => r !== row);
  let target = demoSheet.groups.find(g => (g.lc?.lc_no ?? null) === lcNo);
  if (!target) {
    target = {lc: lcNo ? {id: Date.now(), lc_no: lcNo, opened_on: openedOn} : null, rows: []};
    const unlinked = demoSheet.groups.findIndex(g => g.lc === null);
    demoSheet.groups.splice(lcNo && unlinked >= 0 ? unlinked : demoSheet.groups.length, 0, target);
  }
  if (target.lc) target.lc.opened_on = openedOn;
  target.rows.push(row);
  demoSheet.groups = demoSheet.groups.filter(g => g.rows.length > 0);
  return structuredClone(demoSheet);
}

/** GET /api/cargo/sheet. 로그인한 사용자의 화물 표. L/C별 묶음이고, 마지막 묶음은 L/C가 아직 없을 수 있다. */
export async function getCargoSheet(): Promise<CargoSheet> {
  if (!isLive) return structuredClone(demoSheet);
  return (await call('/api/cargo/sheet', {}, HISTORY_TIMEOUT_MS)).json();
}

/** PUT /api/cargo/sheet/{cargo_key}/lc. 이 B/L을 신용장에 묶는다. lc_no가 null이면 묶음을 푼다. 표 전체를 돌려받는다. */
export async function saveCargoLc(cargoKey: string, lcNo: string | null, openedOn: string | null): Promise<CargoSheet> {
  const body = {lc_no: lcNo, opened_on: lcNo ? openedOn : null};
  if (!isLive) return demoSetLc(cargoKey, body.lc_no, body.opened_on);
  return (await call(`/api/cargo/sheet/${encodeURIComponent(cargoKey)}/lc`, {method: 'PUT', headers: {'content-type': 'application/json'}, body: JSON.stringify(body)}, HISTORY_TIMEOUT_MS)).json();
}

/** PUT /api/cargo/sheet/{cargo_key}/departed. 출항일을 쓴다. source 기본값 manual은 사용자가 직접 적은 값, document는 도착 통지서 사진에서 읽어 사용자가 확인한 값이다. null이면 지운다. 표 전체를 돌려받는다. */
export async function saveCargoDeparted(cargoKey: string, departedOn: string | null, source: 'manual' | 'document' = 'manual'): Promise<CargoSheet> {
  if (!isLive) return demoSetDeparted(cargoKey, departedOn, source);
  const body = JSON.stringify({departed_on: departedOn, source});
  return (await call(`/api/cargo/sheet/${encodeURIComponent(cargoKey)}/departed`, {method: 'PUT', headers: {'content-type': 'application/json'}, body}, HISTORY_TIMEOUT_MS)).json();
}

/** GET /api/cargo/sheet.xlsx. 출입증 헤더가 필요해서 링크 대신 blob으로 받는다. 파일 이름은 Content-Disposition, 없으면 marvia_cargo.xlsx. */
export async function downloadCargoSheet(): Promise<{blob: Blob; filename: string}> {
  if (!isLive) throw new Error('체험 모드에서는 엑셀을 받을 수 없어요.');
  const res = await call('/api/cargo/sheet.xlsx', {}, HISTORY_TIMEOUT_MS);
  const disposition = res.headers.get('content-disposition') ?? '';
  // filename*=UTF-8''... 이 있으면 먼저, 없으면 filename="..."
  const star = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(disposition)?.[1];
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(disposition)?.[1];
  let filename = 'marvia_cargo.xlsx';
  try { filename = (star ? decodeURIComponent(star) : plain) || filename; } catch { /* 깨진 인코딩이면 기본 이름 */ }
  return {blob: await res.blob(), filename};
}

/* ---------- 운영자 관리 (docs/specs/operator-admin.md) ---------- */

/** GET /api/me. 탭을 나누는 데만 쓴다. 관리 API는 서버가 다시 확인한다.
 * 데모 모드는 관리 화면도 볼 수 있게 운영자로 둔다(가공 데이터). 못 읽으면 일반 사용자로 본다. */
export async function getMe(): Promise<MeResponse> {
  if (!isLive) return {user_id: 'demo', email: null, is_operator: true, profile_complete: true};
  try { return await (await call('/api/me', {}, HISTORY_TIMEOUT_MS)).json(); }
  // 정지면 안내 화면으로. 그 밖에 못 읽으면 일반 사용자로 보고 입력 화면으로 막지도 않는다 (user-profile EC-06)
  catch (e) { return {user_id: null, email: null, is_operator: false, profile_complete: true, suspended: e instanceof Error && e.message === SUSPENDED_MESSAGE}; }
}

/** GET /api/admin/customers. 이메일·이름은 서버가 가려서 준다. */
export async function getCustomers(): Promise<CustomersResponse> {
  if (!isLive) { await pause(); return structuredClone(adminFixture.customers) as CustomersResponse; }
  return (await call('/api/admin/customers', {}, HISTORY_TIMEOUT_MS)).json();
}

/** GET /api/admin/operators. 활성 운영자와 등록·해지 이력. */
export async function getOperators(): Promise<OperatorsResponse> {
  if (!isLive) { await pause(); return structuredClone(adminFixture.operators) as OperatorsResponse; }
  return (await call('/api/admin/operators', {}, HISTORY_TIMEOUT_MS)).json();
}

/** 등록·해지는 바뀐 목록을 바로 돌려받는다. 데모 모드에는 바꿀 실제 권한이 없다. */
async function changeOperator(path: string, email: string): Promise<OperatorsResponse> {
  if (!isLive) throw new Error('체험 모드에서는 운영자를 바꿀 수 없어요.');
  const res = await call(path, {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({email: email.trim()})}, HISTORY_TIMEOUT_MS);
  return res.json();
}
export const grantOperator = (email: string) => changeOperator('/api/admin/operators', email);
export const revokeOperator = (email: string) => changeOperator('/api/admin/operators/revoke', email);

/** 고객 한 명 동작 (operator-admin 추가 절). 데모 모드에는 실제 고객이 없어 막는다. */
async function customerCall<T>(path: string, init: RequestInit): Promise<T> {
  if (!isLive) throw new Error('체험 모드에서는 고객 정보를 바꾸거나 열 수 없어요.');
  const res = await call(path, init, HISTORY_TIMEOUT_MS);
  return res.json();
}
const json = (method: string, body: unknown): RequestInit => ({method, headers: {'content-type': 'application/json'}, body: JSON.stringify(body)});
/** 사유를 남기고 원문을 받는다. 서버가 먼저 기록하고, 기록에 실패하면 원문을 주지 않는다 */
export const unmaskCustomer = (id: string, reason: string) =>
  customerCall<UnmaskResponse>(`/api/admin/customers/${encodeURIComponent(id)}/unmask`, json('POST', {reason}));
export const updateCustomer = (id: string, p: ProfileData) =>
  customerCall<{ok: boolean}>(`/api/admin/customers/${encodeURIComponent(id)}/profile`, json('PUT', p));
export const deleteCustomer = (id: string) =>
  customerCall<{deleted_records: number}>(`/api/admin/customers/${encodeURIComponent(id)}`, {method: 'DELETE'});
/** 일시 정지(사유 필수)와 해제. 서버가 Supabase 차단과 정지 표를 같이 바꾼다 */
export const suspendCustomer = (id: string, reason: string) =>
  customerCall<{ok: boolean}>(`/api/admin/customers/${encodeURIComponent(id)}/suspend`, json('POST', {reason}));
export const resumeCustomer = (id: string) =>
  customerCall<{ok: boolean}>(`/api/admin/customers/${encodeURIComponent(id)}/resume`, {method: 'POST'});
export async function getAdminActions(): Promise<ActionItem[]> {
  if (!isLive) return [];
  return (await call('/api/admin/actions', {}, HISTORY_TIMEOUT_MS)).json();
}

/* ---------- 회원 정보 (docs/specs/user-profile.md) ---------- */

/** GET /api/profile. 아직 입력하지 않았으면 null(404). 본인에게만 원문이 온다. */
export async function getProfile(): Promise<ProfileData | null> {
  if (!isLive) return null;
  try {
    return await (await call('/api/profile', {}, HISTORY_TIMEOUT_MS)).json();
  } catch (e) {
    // 아직 입력 전이면 서버가 404 "회원 정보가 없습니다"를 준다 (routers/profile.py). 그때만 null
    if (e instanceof Error && e.message === PROFILE_MISSING) return null;
    throw e;
  }
}
const PROFILE_MISSING = '회원 정보가 없습니다';

/** PUT /api/profile. 동의(consent)가 없으면 서버가 거절한다. 저장은 서버에서 암호화된다. */
export async function saveProfile(p: ProfileData & {consent: boolean}): Promise<ProfileData> {
  if (!isLive) throw new Error('체험 모드에서는 회원 정보를 저장하지 않아요.');
  const res = await call('/api/profile', {method: 'PUT', headers: {'content-type': 'application/json'}, body: JSON.stringify(p)}, HISTORY_TIMEOUT_MS);
  return res.json();
}

/** GET /api/metrics (운영자 전용). 서버가 evals/results의 구성별 최신 결과를 화면 모양으로 준다.
 * 데모 모드는 가공 fixture(값 없음). 못 읽으면 null을 돌려 화면이 fixture(미측정)로 남는다 */
export async function getMetrics(): Promise<typeof metrics | null> {
  if (!isLive) return null;
  try { return await (await call('/api/metrics', {}, HISTORY_TIMEOUT_MS)).json(); }
  catch { return null; }
}

/** 화면 보조 자료(예시 입력, 지표, 설정). 백엔드 endpoint가 아니다. */
export function getPresentationData() { return structuredClone({demo, metrics, settings}); }

/** 개발 중 상태 미리보기. 데모 모드에서만 동작하고 요청 본문에는 아무것도 더하지 않는다. */
export function selectFixture(id: string | null) {
  selectedFixture = !isLive && process.env.NODE_ENV === 'development' && id && responses[id] ? id : null;
}

/** 이력 행의 저장된 판정 다시 보기. GET /api/history는 요약만 주므로 실제 모드에서는 상세가 없다(null).
 * 새로 POST해서 과거 결과인 척하지 않는다. 실제 재생은 상세 endpoint가 생겨야 한다.
 */
export function getReplaySnapshot(requestId: string) {
  if (isLive) return null;
  const entry = Object.entries(responses).find(([, value]) => value.trace_id === requestId);
  if (!entry) return null;
  const choice = demo.choices.find(c => c.id === entry[0]);
  if (!choice) return null;
  selectedFixture = null;
  previous = {key: `${choice.request.session_id}:${choice.request.bl_no}`, response: structuredClone(entry[1])};
  return {response: structuredClone(entry[1]), request: structuredClone(choice.request) as AgentRequest};
}

/** 번들 Natural Earth 지형. 지도 타일 서버를 부르지 않는다 (THIRD_PARTY.md). */
export function getGeography() { return geography; }


/** 감시·지도 화면의 화물 한 건 (docs/specs/cargo-watch.md). 위치는 worker가 6시간마다 모은 마지막 값이다 */
export interface WatchItem {
  bl_masked: string; label: string | null; ship_name: string; status: 'active' | 'done';
  verdict: 'fine' | 'watch' | 'act' | null; stage: string | null; eta: string | null; days_margin: number | null;
  /** 위치는 수집 전이면 null이다 (GET /api/watch). 지도는 위치 있는 화물만 그린다 */
  lat: number | null; lng: number | null; cog: number | null; sog: number | null; position_at: string | null;
  /** 6시간마다(또는 조회할 때마다) 저장한 위치 이력, 오래된 순. 마지막 점이 현재 위치(lat·lng)와 같다 */
  track?: {lat: number; lng: number; at: string; sog: number | null}[];
  /** 서버 목록에만 있는 칸: 화물 지문, UNI-PASS 품명, 배 국적 */
  cargo_key?: string; goods_name?: string | null; ship_flag?: string | null;
}
export interface WatchList { items: WatchItem[]; updated_at: string | null; sample: boolean }
/** 내 감시 화물 목록. 서버(isLive)면 GET /api/watch, 데모 모드면 가공 예시를 돌려준다(sample).
 * 서버는 선명을 모르면 null을 주므로 화면 글자가 비지 않게 가린 B/L로 채운다 */
export async function getWatchList(): Promise<WatchList> {
  if (!isLive) {
    const data = structuredClone(watchMap) as {items: WatchItem[]; updated_at: string};
    return {items: data.items, updated_at: data.updated_at, sample: true};
  }
  const data = (await (await call('/api/watch', {}, HISTORY_TIMEOUT_MS)).json()) as WatchList & {items: (WatchItem & {ship_name: string | null})[]};
  return {...data, items: data.items.map(i => ({...i, ship_name: i.ship_name ?? i.bl_masked}))};
}
