/** B/L 없이 배(MMSI)만 지켜보기의 API 클라이언트 (실사용 57번, 백엔드 routers/watch.py /api/watch/vessels).
 *
 * 왜 api.ts가 아니라 새 파일인가: api.ts는 다른 작업이 같이 고치는 중이라 겹치지 않게 따로 뒀다. 출입증 붙이기·주소 규칙은
 * api.ts의 call과 같다(accessToken, NEXT_PUBLIC_API_BASE). 오류는 서버가 준 안내 문장(detail)을 그대로 올린다.
 * 판정·통관은 없다. 배 이름·국적·목적지·도착 예정은 채팅에서 사용자가 본 글 그대로 보낸다 (서버가 길이만 자른다).
 */
import {accessToken} from './auth';

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? '').trim().replace(/\/+$/, '');
/** 서버가 없으면(체험 모드) 계정이 없어 지켜볼 수 없다 */
export const vesselWatchEnabled = API_BASE !== '';
const TIMEOUT_MS = 15_000;

/** 채팅에서 본 배. dest·eta는 보인 글 그대로(없으면 생략). 입항 예정 목록처럼 MMSI가 없는 곳은 mmsi 대신 callSign을 준다 (서버가 찾는다) */
export interface VesselRef { mmsi?: number | null; callSign?: string | null; name: string; flag?: string | null; dest?: string | null; eta?: string | null }

/** 지켜보는 배 한 척. 위치는 수집 전이면 null이다. 판정 칸은 일부러 없다 */
export interface WatchedVessel {
  mmsi: number; name: string; flag: string | null; dest: string | null; eta: string | null; created_at: string | null;
  lat: number | null; lng: number | null; cog: number | null; sog: number | null; position_at: string | null;
  track: {lat: number; lng: number; at: string; sog: number | null}[];
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const headers = new Headers(init.headers);
    const token = await accessToken();
    if (token) headers.set('authorization', `Bearer ${token}`);
    if (init.body) headers.set('content-type', 'application/json');
    const res = await fetch(`${API_BASE}${path}`, {...init, headers, signal: controller.signal});
    if (!res.ok) {
      let detail = '';
      try { const b = await res.json(); if (typeof b?.detail === 'string') detail = b.detail; } catch { /* JSON이 아니면 기본 문장 */ }
      // 하루 조회 한도(503)는 서버 안내 문장을 그대로, 문장이 없으면 같은 뜻의 기본 문장
      throw new Error(res.status === 401 ? '로그인이 필요해요. 로그인한 뒤 다시 시도해 주세요.' : detail || (res.status === 503 ? '오늘 선박 조회 한도를 다 썼어요. 내일 다시 시도해 주세요.' : '') || '배 지켜보기를 처리하지 못했어요. 잠시 뒤 다시 시도해 주세요.');
    }
    return res;
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw new Error('답이 너무 늦어져 중단했어요. 다시 시도해 주세요.');
    throw e;
  } finally { clearTimeout(timer); }
}

// 켜고 끈 일을 같은 화면의 다른 버튼·목록에 알린다 (WatchToggle이 AppProvider로 하는 것과 같은 목적, 여기서는 api.ts를 안 건드리려고 자체 구독)
type Listener = () => void;
const listeners = new Set<Listener>();
export const onVesselWatchChange = (fn: Listener) => { listeners.add(fn); return () => { listeners.delete(fn); }; };
const notify = () => listeners.forEach(fn => fn());
/** 채팅이 서버에서 배를 넣거나 뺀 뒤, 같은 화면의 지켜보기 버튼·목록이 새로 읽게 알린다 */
export const notifyVesselWatchChange = notify;

/** GET /api/watch/vessels. 체험 모드면 빈 목록 */
export async function listWatchedVessels(): Promise<WatchedVessel[]> {
  if (!vesselWatchEnabled) return [];
  return ((await (await request('/api/watch/vessels')).json()) as {items: WatchedVessel[]}).items;
}

/** POST /api/watch/vessels. 같은 배를 다시 올리면 보인 값만 갱신된다. 5척 한도면 서버 안내 문장으로 실패한다.
 * 호출부호로 올렸을 때 서버가 정한 MMSI를 돌려준다 (해제할 때 쓴다). 서버가 번호를 못 정하면 안내 문장으로 실패한다 */
export async function watchVessel(v: VesselRef): Promise<number> {
  if (!vesselWatchEnabled) throw new Error('체험 모드에서는 배를 지켜볼 수 없어요.');
  const body = v.mmsi ? {mmsi: v.mmsi} : {call_sign: v.callSign ?? null};
  const res = await request('/api/watch/vessels', {method: 'POST', body: JSON.stringify({...body, name: v.name, flag: v.flag ?? null, dest: v.dest ?? null, eta: v.eta ?? null})});
  const mmsi = ((await res.json()) as {mmsi: number}).mmsi;
  notify();
  return mmsi;
}

/** DELETE /api/watch/vessels/{mmsi}. 켜져 있지 않아도 오류가 아니다 */
export async function unwatchVessel(mmsi: number): Promise<void> {
  if (!vesselWatchEnabled) return;
  await request(`/api/watch/vessels/${mmsi}`, {method: 'DELETE'});
  notify();
}
