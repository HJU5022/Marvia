/** ETA field names match C1. trusted_eta is rendered, never recomputed by the UI. */
import {Check,Clock3} from 'lucide-react';
import type {AgentResponse} from '@/lib/types';
import {dateTime} from '@/lib/format';
import {Empty,SectionTitle} from './Shared';
export function EtaCompare({response:r}:{response:AgentResponse}) {
 const rows=[['AIS 보고',r.eta?.ais_eta],['해수부 입항 예정',r.eta?.mof_eta],['거리·속도 계산',r.eta?.calc_eta]];
 return <section className="eta-section"><SectionTitle label="언제 도착하나요?" kicker="ETA CROSS-CHECK" side={<Clock3 size={18}/>}/>{!r.eta?<Empty>입항 예정 정보가 없습니다.</Empty>:<><div className="eta-list">{rows.map(([label,value],i)=><div key={label} className={`eta-row ${value&&value===r.eta?.trusted_eta?'adopted':''} ${i===0&&r.position?.freshness==='stale'?'outdated':''}`}><span>{label}{i===0&&r.position?.freshness==='stale'&&<small>오래된 AIS 근거</small>}</span><div><strong>{value?dateTime(value,true):'확인되지 않음'}</strong>{value&&value===r.eta?.trusted_eta&&<small><Check size={12}/> 신뢰 ETA와 일치</small>}</div></div>)}</div><div className="eta-note"><span>채택 시각</span><strong>{dateTime(r.eta.trusted_eta,true)}</strong><p>{r.conflicts.length?r.conflicts.map(c=>c.why).join(' '):'응답의 신뢰 ETA를 표시합니다. 별도 채택 사유는 제공되지 않았습니다.'}</p></div></>}</section>;
}
