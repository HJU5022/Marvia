/** Presentation only: all timestamps use Asia/Seoul; unknown values never become zero. */
import type { Status, Verdict } from './types';
export const statusLabels: Record<Status, string> = {ok:'조회 완료',partial:'부분 응답',insufficient:'정보 확인 필요',failed:'조회 실패',unsupported:'지원 범위 밖'};
export const verdictLabels: Record<Verdict, string> = {fine:'괜찮음',watch:'지켜볼 것',act:'지금 조치'};
export const sourceLabels: Record<string, string> = {shipfinder:'ShipFinder',unipass:'UNI-PASS',mof:'해양수산부',searoute:'해상 거리 계산',rule:'판정 규칙'};
export function maskBl(value: string) { return `•••• ${value.replace(/\s/g,'').slice(-4)}`; }
export function dateTime(value: string | null | undefined, short = false) {
  if (!value) return '확인되지 않음';
  const d = new Date(value);
  if (Number.isNaN(d.valueOf())) return '확인되지 않음';
  return new Intl.DateTimeFormat('ko-KR', {timeZone:'Asia/Seoul', ...(short ? {} : {year:'numeric' as const}), month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(d);
}
export function day(value: string | null | undefined) { return value?.slice(0,10).replaceAll('-','.') ?? '확인되지 않음'; }
export function shown(value: unknown) { return value === null || value === undefined || value === '' ? '확인되지 않음' : String(value); }
