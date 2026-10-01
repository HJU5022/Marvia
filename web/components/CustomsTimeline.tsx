/** Backend history is list[dict]. Missing keys are safely displayed, not inferred. */
import {ArrowRight,Container,PackageCheck} from 'lucide-react';
import type {AgentResponse} from '@/lib/types';
import {dateTime,shown} from '@/lib/format';
import {Empty,SectionTitle} from './Shared';
export function CustomsTimeline({response:r}:{response:AgentResponse}) {
 const c=r.customs;return <section className="customs-section"><SectionTitle label="입항부터 반출까지" kicker="CUSTOMS JOURNEY" side={<PackageCheck size={19}/>}/>{c?<><div className="current-stage"><span className="eyebrow">현재 통관 단계 · {c.stage_code||'코드 없음'}</span><h3>{c.stage_name}</h3><p>{c.plain_explanation}</p></div><ol className="timeline">{c.history.map((h,i)=><li key={i}><span className="timeline-point"/><div><strong>{shown(h.name)}</strong><small>{typeof h.at==='string'?dateTime(h.at,true):'시각 확인되지 않음'}{h.code?` · ${String(h.code)}`:''}</small></div></li>)}</ol><div className="next-stage"><ArrowRight size={15}/><span>다음 단계 <strong>{c.next_stage??'확인되지 않음'}</strong></span></div><p className="broker-note">{c.needs_broker?'관세사 확인이 필요한 단계입니다.':'응답 기준 관세사 확인 요청 없음'}</p></>:<Empty>이번 응답에 통관 단계 정보가 없습니다.</Empty>}<div className="berth-info"><Container size={19}/><div><span>접안 시설</span><strong>{shown(r.berth?.facility)}</strong><span>장치장 · {shown(r.berth?.shed)}</span></div></div></section>;
}
