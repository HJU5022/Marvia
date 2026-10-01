/** 실제 백엔드 연결 시 이 함수 안만 fetch로 바꾸면 된다.
 * getAgentResponse: POST /api/agent, body = AgentRequest, result = AgentResponse.
 * getHistory: GET /api/history?session_id=..., result = {items, available}.
 * Below these two functions are local presentation/replay helpers, not backend APIs.
 * No remote requests, credentials, or LLM calls are included. SDD 4.3/4.4, E9.
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

const responses: Record<string, AgentResponse> = {ok, partial, insufficient, failed, unsupported, watch, act} as Record<string, AgentResponse>;
let selectedFixture: string | null = null;
let previous: { key: string; response: AgentResponse } | null = null;
const pause = () => new Promise<void>(resolve => setTimeout(resolve, 1050));

/** Preserve the exact wire request. Scenario selection is deliberately out of band. */
export async function getAgentResponse(req: AgentRequest): Promise<AgentResponse> {
  await pause();
  const normalized = req.bl_no.replace(/\s/g, '').toUpperCase();
  if (!/^[A-Z0-9]{8,20}$/.test(normalized)) throw new Error('B/L은 영문·숫자 8~20자로 입력해 주세요.');
  if ((req.follow_up_question?.length ?? 0) > 300) throw new Error('질문은 300자 이내로 입력해 주세요.');
  const key = `${req.session_id}:${normalized}`;
  const choice = demo.choices.find(c => c.request.bl_no === normalized);
  if (choice && (req.sale_due_date !== choice.request.sale_due_date || req.bl_type !== choice.request.bl_type)) {
    throw new Error('저장된 예시와 조회 조건이 다릅니다. 예시 화물을 다시 선택하면 저장된 판매 예정일·B/L 구분으로 돌아갑니다.');
  }
  const id = selectedFixture ?? choice?.id;
  if (!id || !responses[id]) throw new Error('저장된 예시 B/L이 없습니다. 상단에서 예시 화물을 선택해 주세요.');
  let result = structuredClone(responses[id]);
  // Explicit fixtures simulate one documented resolution, not an invented matching algorithm.
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

/** Match the backend envelope, including unavailable vs an empty history. */
export async function getHistory(sessionId: string): Promise<HistoryResponse> {
  await new Promise<void>(resolve => setTimeout(resolve, 180));
  return sessionId === demo.session_id ? structuredClone(history) as HistoryResponse : {items: [], available: true};
}

/** Local UI fixtures are kept separate from the two wire contracts. */
export function getPresentationData() { return structuredClone({demo, metrics, settings}); }

/** Development-only override never adds fixture/status fields to AgentRequest. */
export function selectFixture(id: string | null) {
  selectedFixture = process.env.NODE_ENV === 'development' && id && responses[id] ? id : null;
}

/** Offline E11 snapshots: current GET /history has no response/detail field.
 * Never pretend a new POST can reproduce the old response. A real detail endpoint
 * is required for backend history replay; see NOTES.md.
 */
export function getReplaySnapshot(requestId: string) {
  const entry = Object.entries(responses).find(([, value]) => value.trace_id === requestId);
  if (!entry) return null;
  const choice = demo.choices.find(c => c.id === entry[0]);
  if (!choice) return null;
  // A replay becomes the active session context; clear any dev scenario from the last query.
  selectedFixture = null;
  previous = {key: `${choice.request.session_id}:${choice.request.bl_no}`, response: structuredClone(entry[1])};
  return {response: structuredClone(entry[1]), request: structuredClone(choice.request) as AgentRequest};
}

/** Bundled Natural Earth geography. Static data only; Leaflet needs no tile URL. */
import geography from './fixtures/geography.json';
export function getGeography() { return geography; }
