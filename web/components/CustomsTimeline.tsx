/** 통관 단계. part="summary"는 상세 패널 4번 줄(지금 단계 + ⓘ + 다음 단계, 포워더·선사·컨테이너는 값이 있는 칸만, 마누스 시안 2-2),
 * part="history"는 펼쳐 보기 안의 통관 이력과 접안 시설이다. 화물 경로(적재항 → 양륙항, UNI-PASS 값 그대로)는 일정 줄(EtaCompare)로 옮겼다.
 * 이력은 list[dict]라 빈 칸은 그대로 보인다 */
import {Container} from 'lucide-react';
import type {AgentResponse} from '@/lib/types';
import {dateTime,shown} from '@/lib/format';
import {Empty} from './Shared';
import {InfoTip} from './VerdictCard';
export function CustomsTimeline({response:r,part='summary'}:{response:AgentResponse;part?:'summary'|'history'}) {
 const c=r.customs;
 if(part==='history')return <section className="customs-history"><h3 className="fold-sub">입항부터 반출까지</h3>{c?<ol className="timeline">{c.history.map((h,i)=><li key={i}><span className="timeline-point"/><div><strong>{shown(h.name)}</strong><small>{typeof h.at==='string'?dateTime(h.at,true):'시각 확인 안 됨'}</small></div></li>)}</ol>:<Empty>이번 조회에는 통관 단계 정보가 없어요.</Empty>}<div className="berth-info"><Container size={19}/><div><span>접안 부두</span><strong>{shown(r.berth?.facility)}</strong><span>장치장 · {shown(r.berth?.shed)}</span></div></div></section>;
 return <section className="customs-section" aria-label="통관 진행"><div className="customs-head"><h2>통관 진행</h2></div>{c?<>
  <div className="current-stage"><h3>{c.stage_name}<InfoTip label={`${c.stage_name} 설명`}>{c.plain_explanation}</InfoTip></h3><p className="next-stage">다음 단계 <strong>{c.next_stage??'확인 안 됨'}</strong>{c.needs_broker?<span className="subtle-badge">관세사 확인 필요</span>:<span className="broker-note">관세사에게 따로 확인할 일은 없어요</span>}</p></div>
  {(c.forwarder_name||c.carrier_name||c.container_no)&&<dl className="cargo-parties" aria-label="포워더·선사·컨테이너">{c.forwarder_name&&<div><dt>포워더</dt><dd>{c.forwarder_name}</dd></div>}{c.carrier_name&&<div><dt>선사</dt><dd>{c.carrier_name}</dd></div>}{c.container_no&&<div><dt>컨테이너</dt><dd className="mono">{c.container_no}</dd></div>}</dl>}
 </>:<Empty>이번 조회에는 통관 단계 정보가 없어요.</Empty>}</section>;
}
