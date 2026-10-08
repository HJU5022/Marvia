import type {VesselItem} from '@/lib/types';

/** 선박 검색 답 말풍선에 표로 보이는 척 수. 백엔드 services/chat.py SHIP_LIST_SHOWN과 같은 값이어야 글 줄과 표 줄이 같다 */
export const SHIP_LIST_SHOWN = 5;

/** 말풍선 표 한 줄. 서버 값 그대로이고 화면이 계산하지 않는다 */
export interface ShipRow { ship_name: string; expected_arrival: string | null; previous_port: string | null }
/** 말풍선 표 데이터. more는 표에 못 담은 나머지 척 수 */
export interface ShipList { rows: ShipRow[]; more: number }

/** 백엔드 _ship_list_lines와 같은 규칙: 수입 화물선이 있으면 그 배들만, 없으면 전체에서 앞 SHIP_LIST_SHOWN척.
 * 목록은 서버가 이미 입항 예정 시각순으로 정렬해 보낸 순서 그대로다. 배가 없으면 null (표를 그리지 않는다).
 * 대화 상태·탭 저장소에 큰 목록을 쌓지 않으려고 표에 필요한 앞쪽 줄만 남긴다 */
export function shipListOf(vessels: VesselItem[] | undefined | null): ShipList | null {
  if (!vessels?.length) return null;
  const cargo = vessels.filter(v => v.is_cargo);
  const picked = cargo.length ? cargo : vessels;
  return {rows: picked.slice(0, SHIP_LIST_SHOWN).map(v => ({ship_name: v.ship_name, expected_arrival: v.expected_arrival, previous_port: v.previous_port})), more: Math.max(0, picked.length - SHIP_LIST_SHOWN)};
}

const WEEKDAY = ['일', '월', '화', '수', '목', '금', '토'];
/** "10/7 (화) 00:00" (한국 시간, 월·일 앞 0 없음). ISO가 아니면 보인 글 그대로, 없으면 "-" */
export function arrivalLabel(value: string | null | undefined): string {
  if (!value) return '-';
  const d = new Date(value);
  if (Number.isNaN(d.valueOf())) return value;
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', weekday: 'short'}).formatToParts(d).map(x => [x.type, x.value]));
  const wd = WEEKDAY[['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(p.weekday)] ?? '';
  return `${Number(p.month)}/${Number(p.day)} (${wd}) ${p.hour}:${p.minute}`;
}

/** 표를 그릴 때 글에서 뺄 줄: "· "로 시작하는 배 줄과 "외 N척" 줄. 선박 검색 답(kind vessels)에서 표가 있을 때만 쓴다 (코드가 쓴 고정 모양, backend _ship_list_lines) */
export function stripShipLines(text: string): string {
  return text.split('\n').filter(l => !l.startsWith('· ') && !/^외 \d+척$/.test(l.trim())).join('\n');
}
