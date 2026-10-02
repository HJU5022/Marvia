/** 화면이 백엔드와 주고받는 유일한 통로 (SDD 4.3, 4.4, 5.13).
 *
 * 두 모드가 있다. 빌드할 때 NEXT_PUBLIC_API_BASE가 정해 준다.
 * - 실제 모드(값 있음): POST /api/agent, GET /api/history를 그 주소로 부른다
 * - 데모 모드(값 없음): lib/fixtures의 가공 응답만 쓴다. 키도 서버도 없이 화면 전체를 볼 수 있다
 * 화면 컴포넌트는 어느 모드인지 몰라도 된다. 요청·응답 모양은 backend/app/schemas/agent.py(C1, C2) 그대로다.
 * 서버 API 키는 여기에 두지 않는다. NEXT_PUBLIC_* 값은 브라우저에 그대로 보이기 때문이다 (SDD 7절).
 */
import type { AgentRequest, AgentResponse, CustomersResponse, DocumentFactsRequest, DocumentFactsResponse, DocumentResponse, HistoryResponse, MemoryResponse, MeResponse, OperatorsResponse, ProfileData, UnmaskResponse, ActionItem, ChatResponse, VesselDetailResponse } from './types';
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
import geography from './fixtures/geography.json';
import documentFixture from './fixtures/document.json';
import adminFixture from './fixtures/admin.json';
import memoryFixture from './fixtures/memory.json';

/** 끝 슬래시를 뗀 백엔드 주소. 비어 있으면 데모 모드다. */
/** 정지된 계정에 서버가 403 account_suspended를 줄 때 보여 줄 문장. getMe가 이 문장으로 정지를 알아본다 */
export const SUSPENDED_MESSAGE = '운영자가 이 계정을 일시 정지했습니다. 문의가 필요하면 운영자에게 연락해 주세요.';

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? '').trim().replace(/\/+$/, '');
export const isLive = API_BASE !== '';

/** 판정은 LLM 호출과 재시도(validate 3단계, SDD 5.7)까지 기다려야 해서 넉넉히 잡는다. 이력은 DB 읽기뿐이다. */
const AGENT_TIMEOUT_MS = 90_000;
const HISTORY_TIMEOUT_MS = 15_000;
/** 서류 사진은 OCR(1~2초, 누운 사진은 3번)과 소형 LLM 한 번이다 (routers/document.py). */
const DOCUMENT_TIMEOUT_MS = 60_000;
/** routers/document.py MAX_BYTES와 같다. 보내기 전에 막아 큰 파일을 올리느라 기다리지 않게 한다 */
export const DOCUMENT_MAX_BYTES = 10 * 1024 * 1024;

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
// 422 응답의 칸 이름(C2 요청 필드)을 화면 말로. 모르는 칸은 "입력한 값"으로 쓴다 (10-02 화면 용어 점검)
const FIELD_NAMES: Record<string, string> = {
  bl_no: 'B/L 번호', sale_due_date: '판매 예정일', bl_type: 'B/L 구분', voyage_no: '항차 번호',
  forwarder_eta: '포워더 안내 입항 예정일', follow_up_question: '질문', message: '입력한 문장', resolved_mmsi: '선택한 선박',
};
async function errorMessage(res: Response): Promise<string> {
  let detail = '';
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string') detail = body.detail;
    // 422는 detail이 [{loc, msg}] 목록이다. 첫 칸 이름만 보여 준다
    else if (Array.isArray(body?.detail) && body.detail[0]) detail = `${FIELD_NAMES[String(body.detail[0].loc?.at(-1) ?? '')] ?? '입력한 값'}을(를) 확인해 주세요.`;
  } catch { /* 본문이 JSON이 아니면 상태 코드로만 안내한다 */ }
  if (res.status === 401) return '로그인이 필요합니다. 로그인한 뒤 다시 시도해 주세요.';
  if (res.status === 413 || detail === 'too_large') return '사진이 너무 큽니다. 10MB 이하로 올려 주세요.';
  if (detail === 'invalid_image') return '사진을 읽지 못했습니다. JPG·PNG 사진인지 확인해 주세요.';
  if (res.status === 503) return detail || '저장소에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.';
  if (detail === 'account_suspended') return SUSPENDED_MESSAGE;
  if (res.status === 403) return detail || '운영자만 쓸 수 있습니다.';
  if (res.status === 409) return detail || '이미 처리된 요청입니다.';
  if (res.status === 429) return '요청이 많습니다. 잠시 뒤 다시 시도해 주세요.';
  if (res.status === 400 || res.status === 422) return detail || '입력값을 확인해 주세요.';
  return detail || '요청을 처리하지 못했습니다. 잠시 뒤 다시 시도해 주세요.';
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
    if (!res.ok) throw new Error(await errorMessage(res));
    return res;
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw new Error('응답이 너무 오래 걸려 중단했습니다. 다시 시도해 주세요.');
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
        throw new Error('서버에 연결하지 못했습니다. 인터넷 연결을 확인하고 잠시 뒤 다시 시도해 주세요.');
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

/** 이력은 부가 기능이다. 못 읽으면 화면을 죽이지 않고 available:false로 돌려준다 (routers/history.py와 같은 원칙). */
async function liveHistory(): Promise<HistoryResponse> {
  try {
    const res = await call(`/api/history?session_id=${encodeURIComponent(currentSessionId())}`, {}, HISTORY_TIMEOUT_MS);
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

/** 데모: 사진 내용과 상관없이 저장된 가공 추출 결과를 돌려준다. 화면에 가공 예시임을 표시한다. */
async function demoDocument(): Promise<DocumentResponse> {
  await pause();
  return structuredClone(documentFixture) as DocumentResponse;
}

/** 데모: LLM 없이 문장 속 예시 B/L만 알아본다. 배 검색은 가공 예시 표 (실제 모드에서는 서버가 LLM으로 처리) */
async function demoChat(message: string, context: AgentRequest | null): Promise<ChatResponse> {
  const empty = {agent: null, request: null, vessels: [], place: null, ports: [], days: null};
  const bl = message.toUpperCase().match(/MRVDEMO\d{4}/)?.[0];
  const choice = bl ? demo.choices.find(c => c.request.bl_no === bl) : undefined;
  if (choice) {
    const request = choice.request as AgentRequest;
    const agent = await demoAgentResponse(request);
    return {...empty, kind: 'cargo', reply: agent.answer, agent, request};
  }
  if (/배|선박|입항/.test(message)) {
    await pause();
    return {...empty, kind: 'vessels', ...structuredClone(demo.vessel_search), reply: demo.vessel_search.reply} as ChatResponse;
  }
  if (context) {
    const agent = await demoAgentResponse({...context, follow_up_question: message.slice(0, 300)});
    return {...empty, kind: 'cargo', reply: agent.answer, agent, request: context};
  }
  await pause();
  return {...empty, kind: 'message', reply: '데모에서는 예시 B/L(MRVDEMO1101~1107)이 든 문장이나 "중국에서 오는 배"처럼 물어볼 수 있습니다.'};
}

/* ---------- 화면이 쓰는 함수 ---------- */

/** POST /api/agent. 첫 조회, 되묻기 답, 후속 질문이 모두 이 하나로 간다 (SDD 4.3). */
export async function getAgentResponse(req: AgentRequest): Promise<AgentResponse> {
  return isLive ? liveAgentResponse(req) : demoAgentResponse(req);
}

/** POST /api/chat. 문장 하나로 화물 조회·후속 질문·입항 선박 검색. context는 지금 보고 있는 화물(서버 안에서만 쓴다) */
export async function sendChat(message: string, context: AgentRequest | null): Promise<ChatResponse> {
  if (!isLive) return demoChat(message, context);
  const res = await call('/api/chat', {method: 'POST', headers: {'content-type': 'application/json'},
    body: chatBody(message, context)}, AGENT_TIMEOUT_MS);
  return res.json();
}

/** /api/chat과 /api/chat/stream이 같이 쓰는 본문. 화물은 서버에 필요한 칸만 보낸다 */
function chatBody(message: string, context: AgentRequest | null): string {
  const ctx = context ? {bl_no: context.bl_no, bl_type: context.bl_type, sale_due_date: context.sale_due_date ?? null, mrn: context.mrn ?? null} : null;
  return JSON.stringify({message, session_id: currentSessionId(), context: ctx});
}

/** 스트림 통로를 못 쓰는 경우의 표시. 서버가 요청을 받지 않은 것이 확실할 때만 쓴다 (chat-progress.md EC-05) */
class StreamUnavailable extends Error {}

/** POST /api/chat/stream. /api/chat과 같은 답을 주면서, 서버가 실제로 들어간 단계를 onStage로 알려 준다 (docs/specs/chat-progress.md).
 * - 새 통로가 없는 서버(404·405)나 응답 전 연결 실패면 /api/chat으로 한 번 대신 보낸다 (EC-05). 이때 단계 소식은 없다
 * - 응답을 받기 시작한 뒤 끊기면 다시 보내지 않는다. 서버는 이미 유료 호출을 하고 있을 수 있다 (EC-06)
 * - 데모 모드는 서버가 없어 단계 소식도 없다. 단계를 지어내지 않는다 (EC-07) */
export async function sendChatStream(message: string, context: AgentRequest | null,
  onStage: (stage: ProgressStage) => void): Promise<ChatResponse> {
  if (!isLive) return demoChat(message, context);
  try {
    return await liveChatStream(message, context, onStage);
  } catch (e) {
    if (e instanceof StreamUnavailable) return sendChat(message, context);
    throw e;
  }
}

async function liveChatStream(message: string, context: AgentRequest | null,
  onStage: (stage: ProgressStage) => void): Promise<ChatResponse> {
  const controller = new AbortController();
  // 전체 시간 제한은 /api/chat과 같다. 판정 LLM 재시도까지 기다린다
  const timer = setTimeout(() => controller.abort(), AGENT_TIMEOUT_MS);
  const timeout = '응답이 너무 오래 걸려 중단했습니다. 다시 시도해 주세요.';
  try {
    let res: Response;
    try {
      const token = await accessToken();
      const headers = new Headers({'content-type': 'application/json', accept: 'text/event-stream'});
      if (token) headers.set('authorization', `Bearer ${token}`);
      res = await fetch(`${API_BASE}/api/chat/stream`, {method: 'POST', headers, body: chatBody(message, context), signal: controller.signal});
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') throw new Error(timeout);
      if (e instanceof TypeError) throw new StreamUnavailable();  // 응답이 없었다. /api/chat이 재시도까지 맡는다
      throw e;
    }
    if (res.status === 404 || res.status === 405) throw new StreamUnavailable();
    if (!res.ok) throw new Error(await errorMessage(res));  // 로그인·권한·입력 오류는 스트림을 열기 전에 온다
    if (!res.body) throw new Error('이 브라우저에서 답을 읽지 못했습니다. 다시 시도해 주세요.');
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    const parse = createSseParser();
    for (;;) {
      let chunk: ReadableStreamReadResult<string>;
      try { chunk = await reader.read(); }
      catch (e) {
        if (e instanceof DOMException && e.name === 'AbortError') throw new Error(timeout);
        throw new Error('답을 받는 중 연결이 끊겼습니다. 다시 물어봐 주세요.');
      }
      if (chunk.done) break;
      for (const ev of parse(chunk.value)) {
        const data = JSON.parse(ev.data);
        if (ev.event === 'progress' && isStage(data?.stage)) onStage(data.stage);
        else if (ev.event === 'result') { void reader.cancel(); return data as ChatResponse; }
        else if (ev.event === 'error') throw new Error(typeof data?.detail === 'string' ? data.detail : '답하지 못했습니다. 다시 시도해 주세요.');
      }
    }
    throw new Error('답을 받기 전에 연결이 끊겼습니다. 다시 물어봐 주세요.');
  } finally {
    clearTimeout(timer);
  }
}

/** GET /api/vessels/detail. 선박 표에서 선명을 눌렀을 때. 데모 모드는 가공 예시 */
export async function getVesselDetail(callSign: string | null, shipName: string): Promise<VesselDetailResponse> {
  if (!isLive) {
    await pause();
    return {call_sign: callSign, ship_name: shipName, vessel: {mmsi: 990000001, name: shipName, flag: 'Panama', call_sign: callSign, ship_type: 70},
      position: {lat: 33.2, lng: 127.6, sog: 13.5, cog: 82, navistat: 0, dest: 'KRPUS', ais_eta: null, last_time: new Date().toISOString(), freshness: 'fresh'},
      distance: {distance_nm: 140, calc_hours_at_sog: 10.4, calc_eta: null}, schedule: null,
      errors: [{source: 'mof', code: 'demo', message: '가공 예시라 해수부 일정은 없습니다'}]};
  }
  const q = new URLSearchParams({ship_name: shipName, ...(callSign ? {call_sign: callSign} : {})});
  return (await call(`/api/vessels/detail?${q}`, {}, AGENT_TIMEOUT_MS)).json();
}

/** GET /api/history. available:false(못 읽음)와 빈 목록을 구분한다. */
export async function getHistory(sessionId: string = currentSessionId()): Promise<HistoryResponse> {
  return isLive ? liveHistory() : demoHistory(sessionId);
}

/** POST /api/document. 서류 사진에서 조회 값 후보를 읽는다. 크기는 보내기 전에 먼저 본다. */
export async function readDocument(file: File): Promise<DocumentResponse> {
  if (file.size > DOCUMENT_MAX_BYTES) throw new Error('사진이 너무 큽니다. 10MB 이하로 올려 주세요.');
  if (file.type && !file.type.startsWith('image/')) throw new Error('사진 파일(JPG·PNG)만 올릴 수 있습니다.');
  return isLive ? liveDocument(file) : demoDocument();
}

/** DELETE /api/history. 로그인한 사용자의 조회 기록을 전부 지운다. 데모 모드에는 지울 실제 기록이 없다. */
export async function deleteMyHistory(): Promise<{deleted: number}> {
  if (!isLive) throw new Error('데모 모드에는 지울 실제 기록이 없습니다.');
  return liveDelete('/api/history');
}

/** DELETE /api/account. 기록과 계정을 지운다. 실패하면 503이고 다시 누르면 이어서 끝난다 (services/account.py). */
export async function deleteMyAccount(): Promise<{deleted_records: number; account_deleted: boolean}> {
  if (!isLive) throw new Error('데모 모드에는 탈퇴할 계정이 없습니다.');
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
  if (!isLive) throw new Error('데모 모드에는 지울 실제 기억이 없습니다.');
  return liveDelete('/api/memory');
}

/** DELETE /api/memory/items/{id}. 메모 한 줄을 지운다. */
export async function deleteMemoryItem(id: string): Promise<{deleted: number}> {
  if (!isLive) throw new Error('데모 모드에는 지울 실제 기억이 없습니다.');
  return liveDelete(`/api/memory/items/${encodeURIComponent(id)}`);
}

/** POST /api/memory/document-facts. 서류 확인 화면에서 "확인한 값으로 채우기"를 눌렀을 때만 부른다 (10-02 결정 7).
 * 실제 모드 + 로그인 사용자일 때만 보낸다. 아니면 아무것도 하지 않고 null. 부르는 쪽은 실패해도 입력 채우기를 막지 않는다. */
export async function saveDocumentFacts(facts: DocumentFactsRequest): Promise<DocumentFactsResponse | null> {
  if (!isLive || !(await accessToken())) return null;
  const res = await call('/api/memory/document-facts', {method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify(facts)}, HISTORY_TIMEOUT_MS);
  return res.json();
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
  if (!isLive) throw new Error('데모 모드에서는 운영자를 바꿀 수 없습니다.');
  const res = await call(path, {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({email: email.trim()})}, HISTORY_TIMEOUT_MS);
  return res.json();
}
export const grantOperator = (email: string) => changeOperator('/api/admin/operators', email);
export const revokeOperator = (email: string) => changeOperator('/api/admin/operators/revoke', email);

/** 고객 한 명 동작 (operator-admin 추가 절). 데모 모드에는 실제 고객이 없어 막는다. */
async function customerCall<T>(path: string, init: RequestInit): Promise<T> {
  if (!isLive) throw new Error('데모 모드에서는 고객 정보를 바꾸거나 열 수 없습니다.');
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
  if (!isLive) throw new Error('데모 모드에서는 회원 정보를 저장하지 않습니다.');
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
