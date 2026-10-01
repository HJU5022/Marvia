/** 화면이 백엔드와 주고받는 유일한 통로 (SDD 4.3, 4.4, 5.13).
 *
 * 두 모드가 있다. 빌드할 때 NEXT_PUBLIC_API_BASE가 정해 준다.
 * - 실제 모드(값 있음): POST /api/agent, GET /api/history를 그 주소로 부른다
 * - 데모 모드(값 없음): lib/fixtures의 가공 응답만 쓴다. 키도 서버도 없이 화면 전체를 볼 수 있다
 * 화면 컴포넌트는 어느 모드인지 몰라도 된다. 요청·응답 모양은 backend/app/schemas/agent.py(C1, C2) 그대로다.
 * 서버 API 키는 여기에 두지 않는다. NEXT_PUBLIC_* 값은 브라우저에 그대로 보이기 때문이다 (SDD 7절).
 */
import type { AgentRequest, AgentResponse, HistoryResponse } from './types';
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
import geography from './fixtures/geography.json';

/** 끝 슬래시를 뗀 백엔드 주소. 비어 있으면 데모 모드다. */
const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? '').trim().replace(/\/+$/, '');
export const isLive = API_BASE !== '';

/** 판정은 LLM 호출과 재시도(validate 3단계, SDD 5.7)까지 기다려야 해서 넉넉히 잡는다. 이력은 DB 읽기뿐이다. */
const AGENT_TIMEOUT_MS = 90_000;
const HISTORY_TIMEOUT_MS = 15_000;

/** 실제 모드의 예시 B/L. 백엔드 REPLAY_MODE 데모 3건과 같다 (README "키 없이 데모 3건", scripts/make_demo.py).
 * 판매 예정일은 make_demo를 돌린 날에 따라 달라지므로 넣지 않는다. 비워도 조회된다(09-29 선택 입력).
 */
export const liveExamples = [
  {id: 'TESTBL01', label: '정상 · 괜찮음', bl_no: 'TESTBL01', bl_type: 'HOUSE' as const},
  {id: 'TESTBL04', label: '같은 이름 배 2척 · 되묻기', bl_no: 'TESTBL04', bl_type: 'HOUSE' as const},
  {id: 'TESTBL26', label: '위치 권한 없음 · 판정 보류', bl_no: 'TESTBL26', bl_type: 'HOUSE' as const},
];

/* ---------- 세션 ID ---------- */

const SESSION_KEY = 'marvia-session-id';
let memorySession = '';

/** 실제 모드에서 이 브라우저를 구분하는 ID. 이력(GET /api/history)이 이 값으로 묶인다.
 * localStorage가 막힌 창(사생활 보호 모드 등)에서는 탭이 열려 있는 동안만 같은 값을 쓴다.
 * 데모 모드는 fixture 이력과 맞도록 demo.json의 고정 세션을 쓴다.
 */
export function currentSessionId(): string {
  if (!isLive) return demo.session_id;
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
async function errorMessage(res: Response): Promise<string> {
  let detail = '';
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string') detail = body.detail;
    // 422는 detail이 [{loc, msg}] 목록이다. 첫 칸 이름만 보여 준다
    else if (Array.isArray(body?.detail) && body.detail[0]) detail = `입력값을 확인해 주세요 (${String(body.detail[0].loc?.at(-1) ?? '')}).`;
  } catch { /* 본문이 JSON이 아니면 상태 코드로만 안내한다 */ }
  if (res.status === 401) return '로그인이 필요한 서버입니다. 이 화면에는 아직 로그인 기능이 없습니다.';
  if (res.status === 429) return '요청이 많습니다. 잠시 뒤 다시 시도해 주세요.';
  if (res.status === 400 || res.status === 422) return detail || '입력값을 확인해 주세요.';
  return detail || `서버가 요청을 처리하지 못했습니다 (HTTP ${res.status}). 잠시 뒤 다시 시도해 주세요.`;
}

/** 타임아웃을 건 fetch. 연결 자체가 안 되면 주소를 알려 줘서 백엔드가 떠 있는지 확인하게 한다. */
async function call(path: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, {...init, signal: controller.signal});
    if (!res.ok) throw new Error(await errorMessage(res));
    return res;
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw new Error('응답이 너무 오래 걸려 중단했습니다. 다시 시도해 주세요.');
    if (e instanceof TypeError) throw new Error(`백엔드(${API_BASE})에 연결하지 못했습니다. 서버가 켜져 있는지 확인해 주세요.`);
    throw e;
  } finally {
    clearTimeout(timer);
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

/** 이력은 부가 기능이다. 못 읽으면 화면을 죽이지 않고 available:false로 돌려준다 (routers/history.py와 같은 원칙). */
async function liveHistory(): Promise<HistoryResponse> {
  try {
    const res = await call(`/api/history?session_id=${encodeURIComponent(currentSessionId())}`, {}, HISTORY_TIMEOUT_MS);
    return await res.json();
  } catch {
    return {items: [], available: false};
  }
}

/* ---------- 데모 모드 (fixture) ---------- */

const responses: Record<string, AgentResponse> = {ok, partial, insufficient, failed, unsupported, watch, act} as Record<string, AgentResponse>;
let selectedFixture: string | null = null;
let previous: { key: string; response: AgentResponse } | null = null;
const pause = () => new Promise<void>(resolve => setTimeout(resolve, 1050));

/** 저장된 예시 B/L을 그 예시의 조건 그대로만 재생한다. 새 입력에 맞춰 판정을 지어내지 않는다 (NOTES.md). */
async function demoAgentResponse(req: AgentRequest): Promise<AgentResponse> {
  await pause();
  const normalized = req.bl_no.replace(/\s/g, '').toUpperCase();
  if (!/^[A-Z0-9]{8,20}$/.test(normalized)) throw new Error('B/L은 영문·숫자 8~20자로 입력해 주세요.');
  if ((req.follow_up_question?.length ?? 0) > 300) throw new Error('질문은 300자 이내로 입력해 주세요.');
  const key = `${req.session_id}:${normalized}`;
  const choice = demo.choices.find(c => c.request.bl_no === normalized);
  if (choice && ((req.sale_due_date ?? null) !== choice.request.sale_due_date || req.bl_type !== choice.request.bl_type)) {
    throw new Error('저장된 예시와 조회 조건이 다릅니다. 예시 화물을 다시 선택하면 저장된 판매 예정일·B/L 구분으로 돌아갑니다.');
  }
  const id = selectedFixture ?? choice?.id;
  if (!id || !responses[id]) throw new Error('저장된 예시 B/L이 없습니다. 상단에서 예시 화물을 선택해 주세요.');
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

/* ---------- 화면이 쓰는 함수 ---------- */

/** POST /api/agent. 첫 조회, 되묻기 답, 후속 질문이 모두 이 하나로 간다 (SDD 4.3). */
export async function getAgentResponse(req: AgentRequest): Promise<AgentResponse> {
  return isLive ? liveAgentResponse(req) : demoAgentResponse(req);
}

/** GET /api/history. available:false(못 읽음)와 빈 목록을 구분한다. */
export async function getHistory(sessionId: string = currentSessionId()): Promise<HistoryResponse> {
  return isLive ? liveHistory() : demoHistory(sessionId);
}

/** 화면 보조 자료(예시 입력, 지표, 설정). 백엔드 endpoint가 아니다. */
export function getPresentationData() { return structuredClone({demo, metrics, settings}); }

/** 개발 중 상태 미리보기. 데모 모드에서만 동작하고 요청 본문에는 아무것도 더하지 않는다. */
export function selectFixture(id: string | null) {
  selectedFixture = !isLive && process.env.NODE_ENV === 'development' && id && responses[id] ? id : null;
}

/** 이력 행의 저장된 판정 다시 보기. GET /api/history는 요약만 주므로 실제 모드에서는 상세가 없다(null).
 * 새로 POST해서 과거 결과인 척하지 않는다. 실제 재생은 상세 endpoint가 생겨야 한다 (NOTES.md).
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
