/** Presentation only: all timestamps use Asia/Seoul; unknown values never become zero. */
import type { Status, Verdict } from './types';
export const statusLabels: Record<Status, string> = {ok:'조회 완료',partial:'일부만 확인',insufficient:'정보 확인 필요',failed:'조회 실패',unsupported:'지원 범위 밖'};
export const verdictLabels: Record<Verdict, string> = {fine:'순항',watch:'주의',act:'긴급'};
// 출처 이름. 서비스 이름 대신 무엇을 하는 곳인지로 적는다
export const sourceLabels: Record<string, string> = {shipfinder:'선박 위치 신호',unipass:'관세청 통관 조회',mof:'해양수산부 입항 신고',searoute:'해상 거리 계산',rule:'Marvia 계산'};

// 화면에 내부 ID를 그대로 내지 않는다. 모르는 키는 아래 label()이 "기타 항목"으로 바꾼다
// 신호 7종. id는 backend/app/schemas/signals.py SignalId와 같다
export const ruleLabels: Record<string, string> = {
  position_stale:'선박 위치 수신이 끊김', eta_conflict:'도착 예정 시각이 서로 다름', anchor_wait:'항구 앞 대기',
  dest_changed:'목적지가 부산이 아님', navstat_mismatch:'항해 상태와 속력이 안 맞음', customs_hold:'통관 검사·보류',
  sales_date_exceeded:'판매 예정일을 넘김',
};
// 근거 카드 항목. field는 backend/app/services/evidence.py, services/mrn_fallback.py가 붙인다
export const fieldLabels: Record<string, string> = {
  ...ruleLabels,
  ship_name:'선박 이름', stage_name:'현재 통관 단계', entry_date:'입항일', shed_name:'보관 창고',
  position:'선박 위치(위도, 경도)', sog:'속력(노트)', cog:'진행 방향(도)', navistat:'항해 상태', dest:'선박이 밝힌 목적지',
  ais_eta:'선박이 보낸 도착 예정', last_time:'위치 수신 시각', planned_arrival:'입항 예정(해수부 신고)',
  actual_arrival:'실제 입항(해수부)', facility:'접안 부두', distance_nm:'부산까지 남은 거리(해리)',
  calc_hours_at_sog:'지금 속력으로 걸리는 시간', trusted_eta:'가장 믿을 만한 도착 예정', days_margin:'판매 예정일까지 여유(일)',
  calc_eta:'지금 속력 기준 예상 도착', sale_due_date:'판매 예정일', forwarder_eta:'포워더가 알려 준 입항 예정일',
  mrn_plan:'입항 신고 선박', mof_planned:'해수부 입항 예정', mof_eta:'해수부 입항 예정',
};
/** 근거 field를 사람이 읽는 이름으로. 통관 이력은 "stage:단계명"으로 온다.
 * 후속 질문에서 LLM이 부른 도구 근거는 "<도구>.<키>"로 온다 (routers/agent.py _tool_evidence). 키에 이름이 있으면 그 이름을 쓴다.
 * 이름이 있는 항목을 "기타 항목"으로 내지 않는다 (UI 점검 F14) */
export function fieldLabel(field: string) {
  if (field.startsWith('stage:')) return `통관 이력 · ${field.slice(6)}`;
  const key = field.split(/[.:]/).pop() ?? field;
  return fieldLabels[field] ?? fieldLabels[key] ?? '기타 항목';
}
// 숫자 값에 붙일 단위. 근거 값은 서버가 글자로 준다 (Evidence.value). 이름에 단위가 이미 있어도 값만 보는 칸이 있어 값에도 붙인다
const fieldUnits: Record<string, string> = {distance_nm:'해리', sog:'노트', calc_hours_at_sog:'시간', days_margin:'일', cog:'도'};
const ISO_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
/** 근거 카드의 값을 사람이 읽는 모양으로. ISO 시각은 한국 시간으로, 아는 숫자 칸에는 단위를 붙인다. 값 자체는 바꾸지 않는다 (F14) */
export function evidenceValue(field: string, value: string) {
  const v = (value ?? '').trim();
  if (ISO_TIME.test(v)) return dateTime(v);
  const unit = fieldUnits[field.split(/[.:]/).pop() ?? field];
  if (unit && /^-?\d+(\.\d+)?$/.test(v)) return `${v}${unit === '도' ? '°' : ` ${unit}`}`;
  return v || '확인 안 됨';
}

// AIS 항해 상태 코드 (ITU-R M.1371 navigational status)
const navStatus: Record<number, string> = {0:'항해 중',1:'닻을 내리고 정박',2:'조종 불능',3:'조종 제한',4:'선체가 깊어 움직임이 제한됨',5:'부두에 계류',6:'좌초',7:'조업 중',8:'항해 중(돛)',15:'확인 안 됨'};
export function navStatusLabel(code: number | string | null | undefined) {
  if (code === null || code === undefined || code === '') return '확인 안 됨';
  return navStatus[Number(code)] ?? '확인 안 됨';
}
// AIS 선종 코드. 십의 자리로 큰 갈래만 나눈다 (ITU-R M.1371 ship type)
export function shipTypeLabel(code: number | string | null | undefined) {
  const n = Number(code);
  if (code === null || code === undefined || code === '' || Number.isNaN(n)) return '확인 안 됨';
  if (n >= 70 && n < 80) return '화물선';
  if (n >= 80 && n < 90) return '유조선';
  if (n >= 60 && n < 70) return '여객선';
  if (n === 30) return '어선';
  if (n === 31 || n === 32 || n === 52) return '예인선';
  return '기타 선박';
}
/** 국가 코드(KR, PA)를 한국어 이름으로. 모르는 코드는 그대로 둔다 */
export function countryLabel(code: string | null | undefined) {
  if (!code) return '확인 안 됨';
  try { return new Intl.DisplayNames(['ko'], {type:'region'}).of(code.toUpperCase()) ?? code; } catch { return code; }
}
// 선박 검색의 지명은 서버가 영어(China)로 줄 때가 있다 (services/chat.py search_vessels, 사용자 말이 없을 때).
// 나라 이름은 ISO 코드로 바꿔 countryLabel로, 자주 나오는 도시는 한국어 이름으로 적는다. 모르는 이름은 그대로 둔다 (UI 점검 V8)
const placeCodes: Record<string, string> = {CHINA:'CN', JAPAN:'JP', VIETNAM:'VN', 'VIET NAM':'VN', TAIWAN:'TW', 'HONG KONG':'HK', SINGAPORE:'SG',
  THAILAND:'TH', MALAYSIA:'MY', INDONESIA:'ID', PHILIPPINES:'PH', INDIA:'IN', RUSSIA:'RU', 'UNITED STATES':'US', USA:'US', AUSTRALIA:'AU',
  CANADA:'CA', GERMANY:'DE', NETHERLANDS:'NL', KOREA:'KR', 'SOUTH KOREA':'KR'};
const placeNames: Record<string, string> = {SHANGHAI:'상하이', NINGBO:'닝보', QINGDAO:'칭다오', TIANJIN:'톈진', DALIAN:'다롄', XIAMEN:'샤먼',
  SHENZHEN:'선전', TOKYO:'도쿄', OSAKA:'오사카', YOKOHAMA:'요코하마', KOBE:'고베', NAGOYA:'나고야', HAKATA:'하카타', 'HO CHI MINH':'호찌민', HAIPHONG:'하이퐁'};
export function placeLabel(name: string | null | undefined) {
  if (!name) return '';
  const k = name.trim().toUpperCase();
  if (placeNames[k]) return placeNames[k];
  if (placeCodes[k]) return countryLabel(placeCodes[k]);
  return name;
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
  if (!code) return '확인 안 됨';
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
  if (!value) return '확인 안 됨';
  const d = new Date(value);
  if (Number.isNaN(d.valueOf())) return '확인 안 됨';
  // "10월 20일 09:40", 연도까지 필요하면 "2026년 10월 20일 09:40"
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone:'Asia/Seoul', year:'numeric', month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit', hourCycle:'h23'}).formatToParts(d).map(x => [x.type, x.value]));
  return `${short ? '' : `${p.year}년 `}${p.month}월 ${p.day}일 ${p.hour}:${p.minute}`;
}
/** 서버·채팅이 준 시각 글이 ISO면 "10월 8일 08:00"(한국 시간)으로, 아니면 보인 글 그대로 (도착 예정이 2026-10-08T08:00:00+09:00로 그대로 나왔다) */
export function timeOrRaw(value: string | null | undefined) {
  if (!value) return '확인 안 됨';
  return ISO_TIME.test(value.trim()) ? dateTime(value, true) : value;
}
export function day(value: string | null | undefined) { return value ? `${value.slice(0,4)}년 ${Number(value.slice(5,7))}월 ${Number(value.slice(8,10))}일` : '확인 안 됨'; }
export function shown(value: unknown) { return value === null || value === undefined || value === '' ? '확인 안 됨' : String(value); }
/** 판매 예정일까지 여유. days_margin = 판매 예정일 - 신뢰 입항 예정일 (VerdictCard와 같은 말: 음수는 "입항이 판매일보다 늦다") */
export function marginText(c: {days_margin: number | null; sale_due_date: string | null}): string {
  if (c.days_margin === null || c.days_margin === undefined) return c.sale_due_date ? '확인 안 됨' : '판매 예정일 없음';
  return c.days_margin < 0 ? `${Math.abs(c.days_margin)}일 늦음` : `${c.days_margin}일 여유`;
}
