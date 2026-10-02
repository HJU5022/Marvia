/** Presentation only: all timestamps use Asia/Seoul; unknown values never become zero. */
import type { Status, Verdict } from './types';
export const statusLabels: Record<Status, string> = {ok:'조회 완료',partial:'부분 응답',insufficient:'정보 확인 필요',failed:'조회 실패',unsupported:'지원 범위 밖'};
export const verdictLabels: Record<Verdict, string> = {fine:'괜찮음',watch:'지켜볼 것',act:'지금 조치'};
export const sourceLabels: Record<string, string> = {shipfinder:'ShipFinder',unipass:'UNI-PASS',mof:'해양수산부',searoute:'해상 거리 계산',rule:'판정 규칙'};
/** B/L 가운데 절반을 *로 가린다. 서버 mask_bl(schemas/customs.py, SDD 3.5)과 같은 규칙. 예: TESTBL01 → TE****01 */
export function maskBl(value: string) {
  const v = value.replace(/\s/g, '');
  const hidden = v.length ? Math.max(1, Math.floor(v.length / 2)) : 0;
  const start = Math.floor((v.length - hidden) / 2);
  return v.slice(0, start) + '*'.repeat(hidden) + v.slice(start + hidden);
}
export function dateTime(value: string | null | undefined, short = false) {
  if (!value) return '확인되지 않음';
  const d = new Date(value);
  if (Number.isNaN(d.valueOf())) return '확인되지 않음';
  return new Intl.DateTimeFormat('ko-KR', {timeZone:'Asia/Seoul', ...(short ? {} : {year:'numeric' as const}), month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(d);
}
export function day(value: string | null | undefined) { return value?.slice(0,10).replaceAll('-','.') ?? '확인되지 않음'; }
export function shown(value: unknown) { return value === null || value === undefined || value === '' ? '확인되지 않음' : String(value); }
