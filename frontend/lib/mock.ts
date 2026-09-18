// NEXT_PUBLIC_API_BASE 가 없을 때 app/api/ 프록시가 돌려주는 고정 응답. 서버에서만 import 한다.
// 시나리오는 lib/mock-data.json. 경로선은 scripts/fetch_mock_routes.py 로 실제 경로 API 에서 한 번 받아 둔 값이고,
// 출발 시각·여유는 화면 확인용 계산이다. 후보 순위·이유는 사람이 쓴 예시다.
//
// 입력 문장으로 시나리오와 stage 를 고른다.
//   "배포" 또는 "여의도" 포함, 또는 preset=si_deploy → 서울·경기 SI 시나리오 (대중교통 섞임)
//   그 외 → 함정 정비 시나리오 (장거리, 전원 자동차, 픽업 1건)
//   "5명" 포함    → 참석자 5명 (경로선 기본 꺼짐 확인용)
//   "실시간" 포함 → out_of_scope
//   "모름" 포함   → need_info
//   "실패" 포함   → failed
//   "잠정" 포함   → done (provisional)
//   그 외         → need_confirm, 계산 버튼(confirmed_participants)을 누르면 done

import type {
  AgentRequest,
  AgentResponse,
  Candidate,
  CandidateKind,
  GeocodedPin,
  Participant,
  ParticipantPatchRequest,
  ParticipantPatchResponse,
  ParticipantResult,
  Preset,
  Role,
  Slots,
  Transport,
} from "@/types/agent";
import data from "./mock-data.json";

export const MOCK_SESSION_ID = "demo-session";

type LngLat = [number, number];
type ScenarioId = "ship" | "si";

interface PersonSeed {
  name: string;
  origin: string;
  lng: number;
  lat: number;
  transport: Transport;
  role: Role;
  confidence: number;
  owner?: string;
  fifth?: boolean;
  pickup?: string;
  pickup_at?: string;
  pickup_lng?: number;
  pickup_lat?: number;
}

interface CandidateSeed {
  name: string;
  kind: CandidateKind;
  lng: number;
  lat: number;
  rank: number;
  access_ok: boolean;
  reason: string;
  rejected_reason: string | null;
}

interface Scenario {
  preset: Preset;
  datetime: string;
  purpose: string;
  destination: { name: string; lng: number; lat: number };
  meet: string;
  lead_min: number;
  buffer_min: number;
  people: PersonSeed[];
  candidates: CandidateSeed[];
}

interface SavedRoute {
  polyline: LngLat[];
  raw_duration_min: number;
  transfer_count: number | null;
}

const SCENARIOS = data.scenarios as unknown as Record<ScenarioId, Scenario>;
const ROUTES = data.routes as unknown as Record<string, SavedRoute>;

interface Person {
  seed: PersonSeed;
  origin: LngLat;
  confidence: number;
  owner: string | null;
}

interface State {
  scenario: ScenarioId;
  list: Person[];
  last: AgentResponse;
}

function people(sid: ScenarioId, five: boolean): Person[] {
  return SCENARIOS[sid].people
    .filter((p) => five || !p.fifth)
    .map((p) => ({ seed: p, origin: [p.lng, p.lat], confidence: p.confidence, owner: p.owner ?? null }));
}

function participant(x: Person): Participant {
  return {
    name: x.seed.name,
    origin: x.seed.origin,
    transport: x.seed.transport,
    pickup: x.seed.pickup ?? null,
    pickup_at: x.seed.pickup_at ?? null,
    unfamiliar: x.seed.role === "vendor",
    role: x.seed.role,
    owner_user_id: x.owner,
  };
}

function slotsOf(sid: ScenarioId, list: Person[], provisional: boolean): Slots {
  const sc = SCENARIOS[sid];
  return {
    preset: sc.preset,
    datetime: sc.datetime,
    purpose: sc.purpose,
    destination: sc.destination.name,
    participants: list.map(participant),
    rendezvous: null,
    access: { required: true, applied: true, lead_min: sc.lead_min },
    schedule_confirmed: !provisional,
    constraints: [],
    missing: [],
    out_of_scope: false,
  };
}

function geocodedOf(sid: ScenarioId, list: Person[]): GeocodedPin[] {
  const sc = SCENARIOS[sid];
  const pins: GeocodedPin[] = list.map((x) => ({
    name: x.seed.name,
    lng: x.origin[0],
    lat: x.origin[1],
    confidence: x.confidence,
    kind: "participant",
  }));
  pins.push({ ...sc.destination, confidence: 0.9, kind: "destination" });
  for (const x of list) {
    if (x.seed.pickup_at && x.seed.pickup_lng !== undefined && x.seed.pickup_lat !== undefined) {
      pins.push({ name: x.seed.pickup_at, lng: x.seed.pickup_lng, lat: x.seed.pickup_lat, confidence: 0.85, kind: "pickup" });
    }
  }
  return pins;
}

function candidates(sid: ScenarioId): Candidate[] {
  return SCENARIOS[sid].candidates.map((c) => ({
    ...c,
    address: "테스트 주소",
    switched_from: null,
  }));
}

function toMin(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

function hhmm(min: number): string {
  const v = ((min % 1440) + 1440) % 1440;
  return `${String(Math.floor(v / 60)).padStart(2, "0")}:${String(v % 60).padStart(2, "0")}`;
}

function perParticipant(sid: ScenarioId, list: Person[]): ParticipantResult[] {
  const sc = SCENARIOS[sid];
  const arriveBy = toMin(sc.meet) - sc.lead_min;
  const rows: ParticipantResult[] = [];
  for (const cand of sc.candidates.filter((c) => c.rank <= 2)) {
    for (const x of list) {
      const route = ROUTES[`${sid}:${x.seed.name}:${cand.rank}`];
      const picked = Boolean(x.seed.pickup);
      const start: LngLat =
        picked && x.seed.pickup_lng !== undefined ? [x.seed.pickup_lng, x.seed.pickup_lat as number] : x.origin;
      // 받아 둔 경로가 없거나 핀을 옮겼으면 두 점만 잇는다 (백엔드가 있으면 다시 계산된다)
      const moved = !picked && (x.origin[0] !== x.seed.lng || x.origin[1] !== x.seed.lat);
      const polyline: LngLat[] = route && !moved ? route.polyline : [start, [cand.lng, cand.lat]];
      const raw = route?.raw_duration_min ?? 30;
      const total = raw + sc.buffer_min;
      rows.push({
        name: x.seed.name,
        candidate_rank: cand.rank,
        transport: x.seed.transport,
        duration_min: total,
        raw_duration_min: raw,
        buffer_min: sc.buffer_min,
        departure_time: hhmm(arriveBy - total),
        arrive_by: hhmm(arriveBy),
        transfer_count: x.seed.transport === "transit" ? (route?.transfer_count ?? null) : null,
        first_train: null,
        last_train: null,
        polyline,
        via_rendezvous: false,
        via_pickup: picked,
      });
    }
  }
  return rows;
}

function base(stage: AgentResponse["stage"], sid: ScenarioId, list: Person[], provisional = false): AgentResponse {
  return {
    session_id: MOCK_SESSION_ID,
    stage,
    slots: slotsOf(sid, list, provisional),
    result: null,
    questions: [],
    message: "",
    trace_id: `mock-${Date.now()}`,
    geocoded: null,
  };
}

function done(sid: ScenarioId, list: Person[], provisional: boolean): AgentResponse {
  const sc = SCENARIOS[sid];
  const res = base("done", sid, list, provisional);
  res.result = {
    candidates: candidates(sid),
    provisional,
    per_participant: perParticipant(sid, list),
    rendezvous_departure: null,
    confidence: 0.86,
    model_small: "mock-small",
    model_large: "mock-large",
    prompt_version: "mock",
    routed_to: "large",
  };
  res.geocoded = geocodedOf(sid, list);
  const first = sc.candidates.find((c) => c.rank === 1);
  res.message = provisional
    ? "시각이 확정되지 않아 잠정 결과입니다."
    : `${first?.name}에서 ${hhmm(toMin(sc.meet) - sc.lead_min)} 까지 모이는 안을 1순위로 제안합니다.`;
  return res;
}

// 공유 링크 PATCH 를 흉내 내기 위한 서버 메모리 상태 (개발 서버 한정).
let state: State | null = null;

function remember(scenario: ScenarioId, list: Person[], res: AgentResponse): AgentResponse {
  state = { scenario, list, last: res };
  return res;
}

function pickScenario(req: AgentRequest): ScenarioId {
  const text = req.text ?? "";
  if (req.preset === "si_deploy" || text.includes("배포") || text.includes("여의도")) return "si";
  if (req.preset === "ship_maintenance") return "ship";
  return "ship";
}

export function mockAgent(req: AgentRequest): AgentResponse {
  const text = req.text ?? "";

  if (req.confirmed_participants?.length && state) {
    const { scenario } = state;
    const list = state.list.map((x) => {
      const hit = req.confirmed_participants?.find((c) => c.name === x.seed.name);
      return hit ? { ...x, origin: [hit.lng, hit.lat] as LngLat, confidence: 1 } : x;
    });
    return remember(scenario, list, done(scenario, list, false));
  }

  const sid = pickScenario(req);
  const list = people(sid, text.includes("5명"));

  if (text.includes("실시간")) {
    const res = base("out_of_scope", sid, []);
    res.slots = { ...slotsOf(sid, [], false), preset: null, participants: [], out_of_scope: true };
    res.message = "출발 후 실시간 상황(지연·교통 정보)은 도와드릴 수 없습니다. 출발 전 집결 계획만 잡습니다.";
    return res;
  }
  if (text.includes("모름")) {
    const res = base("need_info", sid, list);
    const slots = slotsOf(sid, list, false);
    const second = slots.participants[1];
    slots.participants[1] = { ...second, transport: null };
    slots.missing = ["participants[1].transport", "datetime"];
    slots.datetime = null;
    res.slots = slots;
    res.questions = [`${second.name} 님은 차로 오시나요, 대중교통으로 오시나요?`, "작업은 몇 시에 시작하나요?"];
    res.message = "계산하려면 두 가지가 더 필요합니다.";
    return res;
  }
  if (text.includes("실패")) {
    const res = base("failed", sid, list);
    res.result = {
      ...done(sid, list, false).result!,
      candidates: candidates(sid).map((c) => ({ ...c, rank: null })),
      per_participant: [],
    };
    res.message = "경로 조회에 실패했습니다. 후보 위치만 표시합니다. 잠시 후 다시 시도해 주세요.";
    return res;
  }
  if (text.includes("잠정")) {
    return remember(sid, list, done(sid, list, true));
  }

  const res = base("need_confirm", sid, list);
  res.geocoded = geocodedOf(sid, list);
  res.message = "출발 위치가 맞나요? 핀을 끌어서 고친 뒤 계산을 누르세요.";
  return remember(sid, list, res);
}

export function mockSession(id: string): AgentResponse | null {
  if (id !== MOCK_SESSION_ID) return null;
  if (!state || state.last.stage !== "done") {
    const scenario = state?.scenario ?? "ship";
    const list = state?.list ?? people(scenario, false);
    remember(scenario, list, done(scenario, list, false));
  }
  return state!.last;
}

export type MockPatchResult =
  | { status: 200; body: ParticipantPatchResponse }
  | { status: 403 | 404 | 409; body: { detail: string } };

export function mockPatch(id: string, userId: string, body: ParticipantPatchRequest): MockPatchResult {
  const current = mockSession(id);
  if (!current || !state) return { status: 404, body: { detail: "세션이 없습니다" } };
  const idx = state.list.findIndex((x) => x.seed.name === body.name);
  if (idx < 0) return { status: 404, body: { detail: "참석자가 없습니다" } };
  const person = state.list[idx];

  if (body.claim) {
    if (person.owner && person.owner !== userId) return { status: 409, body: { detail: "already claimed" } };
  } else if (person.owner !== userId) {
    return { status: 403, body: { detail: "not owner" } };
  }

  const list = [...state.list];
  list[idx] = {
    ...person,
    origin: body.claim ? person.origin : [body.lng, body.lat],
    owner: userId,
  };
  const next = done(state.scenario, list, current.result?.provisional ?? false);
  remember(state.scenario, list, next);
  // done 응답에는 슬롯이 반드시 있다 (AgentResponse 계약)
  return { status: 200, body: { slots: next.slots!, result: next.result } };
}
