/** ETA field names match C1. trusted_eta is rendered, never recomputed by the UI.
 * 값이 없는 칸의 "확인되지 않음"은 보통 글꼴로 흐리게 둔다 (UI 점검 V4, 고정폭은 시각에만).
 * "AI에게 근거 묻기"는 입력창에 후속 질문을 채우기만 한다. 보내기는 사용자가 한다 (lib/composer.ts).
 * 한 컴포넌트가 두 자리를 맡는다 (마누스 시안 2-2): part="schedule"은 상세 패널 3번 줄 "출항 ── 지금 ── 입항 예정"(판정 바로 아래, 한 단계 작게),
 * part="sources"는 펼쳐 보기 안의 출처별 도착 예정 비교다. 값은 응답에 있는 것만 쓰고 없으면 "확인되지 않음"이다. */
import {Check,Sparkles} from 'lucide-react';
import {focusComposer} from '@/lib/composer';
import type {AgentResponse} from '@/lib/types';
import {countryLabel,dateTime,portLabel} from '@/lib/format';
import {Empty} from './Shared';
import {InfoTip} from './VerdictCard';
export function EtaCompare({response:r,part='schedule'}:{response:AgentResponse;part?:'schedule'|'sources'}) {
 if(part==='schedule'){
  const c=r.customs,p=r.position;
  // 현재 위치와 입항 예정이 둘 다 모르면 보여 줄 게 출항지뿐이라 줄을 숨긴다
  if(!p&&!r.eta?.trusted_eta)return null;
  const from=c?.loading_port_name??(c?.loading_port?portLabel(c.loading_port):null);
  const to=c?.discharge_port_name??(c?.discharge_port?portLabel(c.discharge_port):null);
  return <section className="schedule-row" aria-label="일정">
   <div className="sch-node"><small>출항</small><strong className={from?undefined:'unknown'}>{from??'확인 안 됨'}</strong>{c?.loading_country&&<em>{countryLabel(c.loading_country)}</em>}</div>
   <span className="sch-line" aria-hidden="true"/>
   <div className="sch-node now"><small><i aria-hidden="true"/>지금</small><strong className={p?'mono':'unknown'}>{p?`${p.lat.toFixed(2)}°N · ${p.lng.toFixed(2)}°E`:'위치 확인 안 됨'}</strong></div>
   <span className="sch-line" aria-hidden="true"/>
   <div className="sch-node end"><small>입항 예정<InfoTip label="입항 예정 설명">입항 예정 ≠ 상품 수령일</InfoTip></small><strong className={r.eta?.trusted_eta?undefined:'unknown'}>{r.eta?dateTime(r.eta.trusted_eta,true):'확인 안 됨'}</strong>{to&&<em>{to}</em>}</div>
  </section>;
 }
 const rows=[['선박이 보낸 도착 예정',r.eta?.ais_eta],['해수부 입항 예정',r.eta?.mof_eta],['남은 거리·속력으로 계산한 도착 예정',r.eta?.calc_eta]];
 return <section className="eta-section"><h3 className="fold-sub">언제 도착하나요?</h3>{!r.eta?<Empty>입항 예정 정보가 없어요.</Empty>:<><div className="eta-list">{rows.map(([label,value],i)=><div key={label} className={`eta-row ${value&&value===r.eta?.trusted_eta?'adopted':''} ${i===0&&r.position?.freshness==='stale'?'outdated':''}`}><span>{label}{i===0&&r.position?.freshness==='stale'&&<small>오래된 위치 신호 기준</small>}</span><div><strong className={value?undefined:'unknown'}>{value?dateTime(value,true):'확인 안 됨'}</strong>{value&&value===r.eta?.trusted_eta&&<small><Check size={12}/> 판단에 쓴 도착 예정</small>}</div></div>)}</div><div className="eta-note"><span>가장 믿을 만한 도착 예정</span><strong>{dateTime(r.eta.trusted_eta,true)}</strong><p>{r.conflicts.length?r.conflicts.map(c=>c.why).join(' '):'출처끼리 어긋나지 않아서 따로 고른 이유는 없어요.'}</p></div></>}<button type="button" className="ask-link" onClick={()=>focusComposer('입항 예정일을 어떤 근거로 정했는지 알려줘')}><Sparkles size={14}/>AI에게 근거 묻기 <span aria-hidden="true">↗</span></button></section>;
}
