'use client';
/** 선박 검색 답(kind 'vessels')의 말풍선. 글 한 덩어리 대신 "요약 한 줄 → 표 → 나머지 보기 → 출처 줄" 네 구역으로 나눈다.
 * 왜: 어르신 사장님들이 "· 이름 · 날짜 · 항구" 줄을 읽기 힘들어했다. 칸 이름을 붙이고 줄을 가른다.
 * 값은 서버가 준 vessels 그대로다(lib/shipList.ts가 백엔드 _ship_list_lines와 같은 규칙으로 앞쪽 줄만 고른다). 서버로 보내는 reply 글은 바꾸지 않고, 화면에서만 표와 겹치는 줄을 뺀다.
 * 표는 넓은 곳에서 한 줄 목록(이름 | 도착 시각, 아래에 직전 기항지). 어느 폭에서나 같은 모양이다 (chat.css .cvt). */
import type {ReactNode} from 'react';
import {useApp} from './AppProvider';
import {EvidencePopover} from './EvidencePopover';
import {arrivalLabel, stripShipLines, type ShipList} from '@/lib/shipList';
import type {Citation, EvidenceItem} from '@/lib/evidenceTypes';

const MARK = /\[E\d+\]/i;

export function ChatVesselTable({text, list, evidence, citations, renderText, latest}: {text: string; list: ShipList; evidence: EvidenceItem[]; citations: Citation[]; renderText: (t: string) => ReactNode; latest: boolean}) {
  const {showVessels, vessels} = useApp();
  // 글에서 표와 겹치는 줄(· 배 줄, "외 N척")만 뺀다. 첫 줄은 요약, 나머지는 출처 안내 줄
  const lines = stripShipLines(text).split('\n').filter(l => l.trim());
  const head = lines[0] ?? '', note = lines.slice(1).join('\n');
  // 출처 칩은 [E#] 표시가 있는 쪽에 둔다. 표시가 어디에도 없으면(서버가 칩 줄만 모으는 경우) 아래 출처 줄 쪽에 둔다.
  // 글을 줄였으니 서버 위치(citations)는 어긋난다. 비워 두면 EvidencePopover가 [E#]를 글에서 다시 찾는다
  const headHas = MARK.test(head);
  const none: EvidenceItem[] = [];
  // "전체 보기"는 가장 최근 검색의 표만 다시 열 수 있다 (화면 상태가 최근 검색 하나만 들고 있다)
  const canOpen = latest && !!vessels;
  return <div className="cvt">
    {head && <p className="cvt-lead"><EvidencePopover text={head} citations={[]} evidence={headHas ? evidence : none} renderText={renderText}/></p>}
    {/* 한 줄 목록: 상자·머리글 없이 배마다 이름(왼쪽)·도착 시각(오른쪽) 한 줄, 그 아래 직전 기항지. 칸 이름은 읽어 주는 도구용 숨은 글자 */}
    <ul className="cvt-list" aria-label="입항 예정 배">{list.rows.map((r, i) => <li key={`${r.ship_name}-${i}`}>
      <div className="cvt-top"><strong className="cvt-name"><span className="sr-only">배 이름 </span>{r.ship_name}</strong>
        <span className="cvt-eta"><span className="sr-only">도착 예정 </span>{arrivalLabel(r.expected_arrival)}</span></div>
      <div className="cvt-port"><span className="sr-only">직전 기항지 </span>{r.previous_port || '-'}</div>
    </li>)}</ul>
    {list.more > 0 && (canOpen
      ? <button type="button" className="cvt-more" onClick={() => { showVessels(); window.dispatchEvent(new Event('marvia:sheet-open')); }}>나머지 {list.more}척 전체 보기</button>
      : <p className="cvt-more-text">외 {list.more}척</p>)}
    {note && <p className="cvt-note"><EvidencePopover text={note} citations={[]} evidence={headHas ? none : evidence} renderText={renderText}/></p>}
  </div>;
}
