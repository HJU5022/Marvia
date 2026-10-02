/** 도착 예정 비교. 필드 이름은 C1과 같다. trusted_eta는 서버 값을 그대로 보여 주고 화면에서 다시 계산하지 않는다. */
import {Check,Clock3} from 'lucide-react';
import type {AgentResponse} from '@/lib/types';
import {dateTime} from '@/lib/format';
import {Empty,SectionTitle} from './Shared';
export function EtaCompare({response:r}:{response:AgentResponse}) {
 const rows=[['선박이 보낸 도착 예정',r.eta?.ais_eta],['해수부 입항 예정',r.eta?.mof_eta],['남은 거리·속력으로 계산',r.eta?.calc_eta]];
 return <section className="eta-section"><SectionTitle label="언제 도착하나요?" kicker="ETA CROSS-CHECK" side={<Clock3 size={18}/>}/>{!r.eta?<Empty>입항 예정 정보가 없습니다.</Empty>:<><div className="eta-list">{rows.map(([label,value],i)=><div key={label} className={`eta-row ${value&&value===r.eta?.trusted_eta?'adopted':''} ${i===0&&r.position?.freshness==='stale'?'outdated':''}`}><span>{label}{i===0&&r.position?.freshness==='stale'&&<small>오래된 위치 신호 기준</small>}</span><div><strong>{value?dateTime(value,true):'확인되지 않음'}</strong>{value&&value===r.eta?.trusted_eta&&<small><Check size={12}/> 채택한 도착 예정</small>}</div></div>)}</div><div className="eta-note"><span>가장 믿을 만한 도착 예정</span><strong>{dateTime(r.eta.trusted_eta,true)}</strong><p>{r.conflicts.length?r.conflicts.map(c=>c.why).join(' '):'출처끼리 어긋나지 않아 따로 고른 이유는 없습니다.'}</p></div></>}</section>;
}
