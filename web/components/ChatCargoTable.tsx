'use client';
/** 한 문장에 B/L이 2~3개일 때 말풍선 아래에 그리는 작은 표 (10-05 정운 결정). 줄 하나가 조회한 화물 하나다.
 * 줄을 누르면 아래 결과 칸이 그 화물로 바뀐다: 서버가 줄마다 준 agent·request를 단일 화물 답과 똑같이 넣는다 (AppProvider.showCargo).
 * 지금 아래 결과 칸에 보이는 화물(첫 줄이 기본)은 request.bl_no와 줄의 request.bl_no가 같은 줄로 표시한다.
 * B/L은 사용자가 입력한 값 그대로다. 값(배 이름, 도착, 여유 일수)은 서버가 준 그대로이고 없는 값은 지어내지 않고 "확인되지 않음"으로 둔다.
 */
import {Check, CircleHelp} from 'lucide-react';
import {useApp} from './AppProvider';
import {VerdictBadge} from './Shared';
import {dateTime, marginText} from '@/lib/format';
import type {ChatCargo} from '@/lib/types';

export function ChatCargoTable({cargos}: {cargos: ChatCargo[]}) {
  const {request, showCargo} = useApp();
  return <div className="chat-cargo-table" role="group" aria-label="조회한 화물 비교">
    <table>
      <thead><tr><th scope="col">B/L · 선박</th><th scope="col">판정</th><th scope="col">입항 예정</th><th scope="col">판매일까지</th></tr></thead>
      <tbody>{cargos.map(c => {
        const on = request.bl_no === c.request.bl_no;
        // 판정을 못 낸 줄은 "판정 없음" 대신 "확인 필요"와 이유를 보인다 (10-06 정운 화면: 무엇이 필요한지 몰랐다)
        const needs = c.status === 'insufficient';
        return <tr key={c.request.bl_no} className={on ? 'on' : undefined}>
          <th scope="row"><button type="button" aria-pressed={on} onClick={() => showCargo(c.agent, c.request)}>
            <span className="mono">{c.bl_no}</span><small>{needs ? c.note : (c.ship_name ?? '선박 확인되지 않음')}</small>{on && <Check size={12} aria-label="아래 결과 칸에 보이는 화물"/>}</button></th>
          <td>{needs ? <span className="verdict-badge neutral"><CircleHelp size={14}/>확인 필요</span> : <VerdictBadge verdict={c.verdict as ChatCargo['agent']['verdict']}/>}</td>
          <td>{needs ? '-' : dateTime(c.eta, true)}</td>
          <td>{needs ? '-' : marginText(c)}</td>
        </tr>;
      })}</tbody>
    </table>
    <p className="chat-cargo-hint">줄을 누르면 지도와 근거가 그 화물로 바뀌어요.</p>
  </div>;
}
