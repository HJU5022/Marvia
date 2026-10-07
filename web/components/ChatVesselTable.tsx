'use client';
/** 선박 검색 답(kind 'vessels')의 말풍선. 글 한 덩어리 대신 "요약 한 줄 → 표 → 나머지 보기 → 출처 줄" 네 구역으로 나눈다 (10-08 정운 실사용 77번).
 * 왜: 어르신 사장님들이 "· 이름 · 날짜 · 항구" 줄을 읽기 힘들어했다. 칸 이름을 붙이고 줄을 가른다.
 * 값은 서버가 준 vessels 그대로다(lib/shipList.ts가 백엔드 _ship_list_lines와 같은 규칙으로 앞쪽 줄만 고른다). 서버로 보내는 reply 글은 바꾸지 않고, 화면에서만 표와 겹치는 줄을 뺀다.
 * 표는 넓은 곳에서 3칸(배 이름 | 도착 예정 | 직전 기항지), 좁은 곳(375px)에서는 줄마다 두 줄 카드(이름 굵게, 아래에 도착 · 항구)로 쌓는다 (chat.css .cvt). */
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
    <div className="cvt-wrap"><table className="cvt-table">
      <caption className="sr-only">입항 예정 배</caption>
      <thead><tr><th scope="col">배 이름</th><th scope="col">도착 예정</th><th scope="col">직전 기항지</th></tr></thead>
      <tbody>{list.rows.map((r, i) => <tr key={`${r.ship_name}-${i}`}>
        <td className="cvt-name">{r.ship_name}</td>
        <td className="cvt-eta"><span className="cvt-lbl">도착 예정 </span>{arrivalLabel(r.expected_arrival)}</td>
        <td className="cvt-port"><span className="cvt-lbl">직전 기항지 </span>{r.previous_port || '-'}</td>
      </tr>)}</tbody>
    </table></div>
    {list.more > 0 && (canOpen
      ? <button type="button" className="cvt-more" onClick={() => { showVessels(); window.dispatchEvent(new Event('marvia:sheet-open')); }}>나머지 {list.more}척 전체 보기</button>
      : <p className="cvt-more-text">외 {list.more}척</p>)}
    {note && <p className="cvt-note"><EvidencePopover text={note} citations={[]} evidence={headHas ? none : evidence} renderText={renderText}/></p>}
  </div>;
}
