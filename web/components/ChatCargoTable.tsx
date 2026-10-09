'use client';
/** 한 문장에 B/L이 2~3개일 때 말풍선 아래에 그리는 비교 카드.
 * 줄 하나가 조회한 화물 하나다. 줄을 누르면 결과 칸이 그 화물로 바뀐다: 서버가 줄마다 준 agent·request를 단일 화물 답과 똑같이 넣는다 (AppProvider.showCargo).
 * 지금 결과 칸에 보이는 화물(첫 줄이 기본)은 request.bl_no와 줄의 request.bl_no가 같은 줄로 표시한다.
 * B/L은 사용자가 입력한 값 그대로다. 값(배 이름, 도착, 여유 일수)은 서버가 준 그대로이고 없는 값은 지어내지 않는다.
 * 시안 3칸: [화물·조회·판정] [선박·도착 예정] [여유·판매일·메모]. 칸 이름은 시안 그대로, 좁은 대화 칸(560px)에 맞춰 줄 안에서 두 줄로 쌓는다.
 * 시안의 실수 수정: 여유 일수를 작은 글씨가 아니라 크고 굵게(색은 판정 등급), 국적을 같이 보인다, 배지는 단일 답과 같은 크기.
 */
import {Check, CircleHelp} from 'lucide-react';
import {useApp} from './AppProvider';
import {VerdictBadge} from './Shared';
import {WatchVesselButton} from './WatchVesselButton';
import {countryLabel, dateTime} from '@/lib/format';
import type {ChatCargo} from '@/lib/types';

/** 조회 상태 짧은 말. 시안 문구 ("조회 정상" · "정보 필요") 를 쓰고, 나머지는 화면 전체에서 쓰는 말과 맞춘다 */
const ROW_STATUS: Record<string, string> = {ok: '조회 완료', partial: '일부만 확인', insufficient: '정보 확인 필요', failed: '조회 실패', unsupported: '지원 범위 밖'};

/** 여유 일수를 크게 보인다. 색은 판정 등급을 따른다(초록 고정 아님). 판매일이 없으면 회색 "판매일 입력 필요" (Manus 2-3 수정) */
function Margin({c}: {c: ChatCargo}) {
  if (c.days_margin === null || c.days_margin === undefined) return <span className="cmp-margin none">{c.sale_due_date ? '미확인' : '판매 예정일 입력 필요'}</span>;
  const late = c.days_margin < 0;
  return <span className={`cmp-margin ${c.verdict ?? ''}`}><b>{late ? `${Math.abs(c.days_margin)}일 늦음` : `${c.days_margin}일 여유`}</b>{c.sale_due_date && <small>판매 예정일 {c.sale_due_date.slice(5).replace('-', '.')}</small>}</span>;
}

export function ChatCargoTable({cargos}: {cargos: ChatCargo[]}) {
  const {request, showCargo} = useApp();
  return <div className="chat-cargo-table cmp-card" role="group" aria-label="조회한 화물 비교">
    <h3 className="cmp-title">화물 {cargos.length}건을 조회했어요.</h3>
    <p className="cmp-sub">줄을 누르면 지도와 근거가 그 화물로 바뀌어요.</p>
    <table className="cmp-table">
      <thead><tr><th scope="col">화물 · 조회 · 판정</th><th scope="col">선박과 도착 예정</th><th scope="col">여유 · 판매 예정일 · 메모</th></tr></thead>
      <tbody>{cargos.map(c => {
        const on = request.bl_no === c.request.bl_no;
        // 판정을 못 낸 줄은 "판정 없음" 대신 "정보 필요"와 이유를 보인다 (무엇이 필요한지 몰랐다)
        const needs = c.status === 'insufficient';
        // 국적은 줄마다 따로 오지 않고 그 화물의 선박 정보(agent.vessel)에 있을 때만 보인다. 없으면 지어내지 않는다
        const flag = c.agent.vessel?.flag ? countryLabel(c.agent.vessel.flag) : null;
        return <tr key={c.request.bl_no} className={on ? 'on' : undefined} onClick={() => showCargo(c.agent, c.request)}>
          <th scope="row"><button type="button" aria-pressed={on} onClick={e => { e.stopPropagation(); showCargo(c.agent, c.request); }}>
            <span className="mono cmp-bl">{c.bl_no}{on && <Check size={14} aria-label="지금 결과에 표시된 화물"/>}</span>
            <span className="cmp-state">
              {needs ? <span className="verdict-badge neutral"><CircleHelp size={16}/>{ROW_STATUS.insufficient}</span> : <>{c.status !== 'ok' && <small>{ROW_STATUS[c.status] ?? c.status}</small>}<VerdictBadge verdict={c.verdict as ChatCargo['agent']['verdict']}/></>}</span>
          </button></th>
          <td>{needs ? <span className="cmp-none">-</span> : <><b className="cmp-ship">{c.ship_name ?? '선박 확인 안 됨'}</b>{flag && <small>{flag}</small>}<span className="cmp-eta">{dateTime(c.eta, true)}</span>
            {/* 배 번호(mmsi)는 그 화물의 agent.vessel에 있을 때만 단다. 없으면 지어내지 않는다. 줄 클릭(화물 바꾸기)과 섞이지 않게 클릭을 막는다 */}
            {c.agent.vessel?.mmsi ? <span className="cmp-watch" onClick={e => e.stopPropagation()}><WatchVesselButton mmsi={c.agent.vessel.mmsi} name={c.ship_name ?? c.agent.vessel.name} flag={c.agent.vessel.flag} eta={c.eta}/></span> : null}</>}</td>
          <td>{needs ? <span className="cmp-note">{c.note ?? '-'}</span> : <Margin c={c}/>}</td>
        </tr>;
      })}</tbody>
    </table>
  </div>;
}
