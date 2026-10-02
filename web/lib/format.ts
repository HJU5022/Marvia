/** Presentation only: all timestamps use Asia/Seoul; unknown values never become zero. */
import type { Status, Verdict } from './types';
export const statusLabels: Record<Status, string> = {ok:'조회 완료',partial:'일부만 확인',insufficient:'정보 확인 필요',failed:'조회 실패',unsupported:'지원 범위 밖'};
export const verdictLabels: Record<Verdict, string> = {fine:'괜찮음',watch:'지켜볼 것',act:'지금 조치'};
// 출처 이름. 서비스 이름 대신 무엇을 하는 곳인지로 적는다 (10-02 화면 용어 점검)
export const sourceLabels: Record<string, string> = {shipfinder:'선박 위치 신호',unipass:'관세청 통관 조회',mof:'해양수산부 입항 신고',searoute:'해상 거리 계산',rule:'Marvia 계산'};

// 화면에 내부 ID를 그대로 내지 않는다. 모르는 키는 아래 label()이 "기타 항목"으로 바꾼다 (10-02 화면 용어 점검)
// 신호 7종. id는 backend/app/schemas/signals.py SignalId와 같다
export const ruleLabels: Record<string, string> = {
  position_stale:'선박 위치 수신이 끊김', eta_conflict:'도착 예정 시각이 서로 다름', anchor_wait:'항구 앞 대기',
  dest_changed:'목적지가 부산이 아님', navstat_mismatch:'항해 상태와 속력이 안 맞음', customs_hold:'통관 검사·보류',
  sales_date_exceeded:'판매 예정일 넘김',
};
// 근거 카드 항목. field는 backend/app/services/evidence.py, services/mrn_fallback.py가 붙인다
export const fieldLabels: Record<string, string> = {
  ...ruleLabels,
  ship_name:'선박 이름', stage_name:'현재 통관 단계', entry_date:'입항일', shed_name:'보관 창고',
  position:'선박 위치(위도, 경도)', sog:'속력(노트)', navistat:'항해 상태', dest:'선박이 밝힌 목적지',
  ais_eta:'선박이 보낸 도착 예정', last_time:'위치 수신 시각', planned_arrival:'입항 예정(해수부 신고)',
  actual_arrival:'실제 입항(해수부)', facility:'접안 부두', distance_nm:'부산까지 남은 거리(해리)',
  calc_hours_at_sog:'지금 속력으로 걸리는 시간', trusted_eta:'가장 믿을 만한 도착 예정', days_margin:'판매 예정일까지 여유(일)',
  calc_eta:'지금 속력 기준 예상 도착', sale_due_date:'판매 예정일', forwarder_eta:'포워더가 알려 준 입항 예정일',
  mrn_plan:'입항 신고 선박', mof_planned:'해수부 입항 예정', mof_eta:'해수부 입항 예정',
};
/** 근거 field를 사람이 읽는 이름으로. 통관 이력은 "stage:단계명"으로 온다 */
export function fieldLabel(field: string) {
  if (field.startsWith('stage:')) return `통관 이력 · ${field.slice(6)}`;
  return fieldLabels[field] ?? '기타 항목';
}

// AIS 항해 상태 코드 (ITU-R M.1371 navigational status)
const navStatus: Record<number, string> = {0:'항해 중',1:'닻을 내리고 정박',2:'조종 불능',3:'조종 제한',4:'흘수 제약',5:'부두에 계류',6:'좌초',7:'조업 중',8:'항해 중(돛)',15:'확인 안 됨'};
export function navStatusLabel(code: number | string | null | undefined) {
  if (code === null || code === undefined || code === '') return '확인되지 않음';
  return navStatus[Number(code)] ?? '확인되지 않음';
}
// AIS 선종 코드. 십의 자리로 큰 갈래만 나눈다 (ITU-R M.1371 ship type)
export function shipTypeLabel(code: number | string | null | undefined) {
  const n = Number(code);
  if (code === null || code === undefined || code === '' || Number.isNaN(n)) return '확인되지 않음';
  if (n >= 70 && n < 80) return '화물선';
  if (n >= 80 && n < 90) return '유조선';
  if (n >= 60 && n < 70) return '여객선';
  if (n === 30) return '어선';
  if (n === 31 || n === 32 || n === 52) return '예인선';
  return '기타 선박';
}
/** 국가 코드(KR, PA)를 한국어 이름으로. 모르는 코드는 그대로 둔다 */
export function countryLabel(code: string | null | undefined) {
  if (!code) return '확인되지 않음';
  try { return new Intl.DisplayNames(['ko'], {type:'region'}).of(code.toUpperCase()) ?? code; } catch { return code; }
}
// 자주 나오는 항구 코드(UN/LOCODE). 없는 코드는 앞 두 글자 나라 이름 + "항구"로 적는다
const ports: Record<string, string> = {
  KRPUS:'부산', KRINC:'인천', KRKAN:'광양', KRUSN:'울산', KRPTK:'평택', CNSHA:'상하이', CNNGB:'닝보', CNQIN:'칭다오',
  CNTAO:'칭다오', CNTXG:'톈진', CNDLC:'다롄', CNXMN:'샤먼', CNSZX:'선전', CNYTN:'옌톈', HKHKG:'홍콩', TWKHH:'가오슝',
  JPOSA:'오사카', JPTYO:'도쿄', JPYOK:'요코하마', JPUKB:'고베', JPNGO:'나고야', JPHKT:'하카타', SGSIN:'싱가포르',
  VNSGN:'호찌민', VNHPH:'하이퐁', THLCH:'람차방', USLAX:'로스앤젤레스', USLGB:'롱비치', NLRTM:'로테르담', DEHAM:'함부르크',
};
/** 항구 코드나 AIS 목적지 문자열을 이름으로. 읽을 수 없으면 원문 대신 "확인되지 않음" */
export function portLabel(code: string | null | undefined) {
  if (!code) return '확인되지 않음';
  const k = code.replace(/[\s-]/g, '').toUpperCase();
  if (ports[k]) return ports[k];
  if (/^[A-Z]{5}$/.test(k)) { const c = countryLabel(k.slice(0, 2)); return c === k.slice(0, 2) ? code : `${c}의 항구`; }
  return code;
}
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
