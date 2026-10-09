'use client';
/** 되묻기: 같은 이름의 배가 여러 척이거나 정보가 모자랄 때 후보를 고르고 부족한 값을 채운다 (Manus 2-3 시안으로 다시 짬).
 * E6 sends only C2 resolved_mmsi/voyage_no/forwarder_eta/bl_type as requested.
 * 후보는 한 줄 카드(이름 · 국적/목적지/마지막 수신 · 후보 이유)와 오른쪽 "선택" 버튼이다. 눌러서 고르고 아래 "확인하고 판정 진행"으로 보낸다.
 * 라디오 입력은 화면 밖에 그대로 두어 키보드(방향키·스페이스)와 스크린리더 동작을 지킨다.
 */
import {useState,type FormEvent} from 'react';
import {ArrowRight,Check} from 'lucide-react';
import type {AgentResponse,AgentRequest} from '@/lib/types';
import {countryLabel,dateTime,portLabel,shipTypeLabel} from '@/lib/format';
import {useApp} from './AppProvider';
import {isLive} from '@/lib/api';
export function CandidatePicker({response:r,request,onResolve,busy}:{response:AgentResponse;request:AgentRequest;onResolve:(req:AgentRequest)=>void;busy:boolean}) {
 const {docHints}=useApp();
 // 서류 사진에서 확인한 항차·입항 예정일이 있으면 미리 채운다 (DocumentPanel). 사용자가 고칠 수 있다
 const [selected,setSelected]=useState<number|null>(null),[voyage,setVoyage]=useState(docHints?.voyage_no??''),[eta,setEta]=useState(docHints?.forwarder_eta??''),[type,setType]=useState(request.bl_type),[error,setError]=useState('');
 function submit(e:FormEvent){e.preventDefault();if(!selected&&!voyage.trim()&&!eta&&!r.missing_inputs.includes('bl_type')){setError('후보를 고르거나 필요한 추가 정보를 입력해 주세요.');return;}setError('');onResolve({...request,follow_up_question:null,resolved_mmsi:selected,voyage_no:voyage.trim()||null,forwarder_eta:eta||null,bl_type:type});}
 const known=['voyage_no','forwarder_eta','bl_type','bl_not_found'];
 const many=r.vessel_candidates.length>1;
 // 세관에 화물이 없을 때(routers/agent.py NO_CARGO)는 후보 없이 B/L 구분만 다시 묻는다. 이때 "판단할게요" 제목은 진행 중처럼 보이고
 // 같은 문장이 왼쪽 채팅 답에 이미 있어 되풀이된다
 const noCargo=!r.vessel_candidates.length&&r.missing_inputs.length===1&&(r.missing_inputs[0]==='bl_type'||r.missing_inputs[0]==='bl_not_found');
 // bl_not_found: 구분을 말하지 않아 서버가 하우스·마스터를 둘 다 조회했는데 없음. 구분을 다시 고르게 할 필요가 없어 선택칸과 버튼을 그리지 않는다
 const triedBoth=noCargo&&r.missing_inputs[0]==='bl_not_found';
 const needsExtra=known.filter(k=>k!=='bl_not_found').some(k=>r.missing_inputs.includes(k))||r.missing_inputs.some(x=>!known.includes(x));
 return <section className="candidate-section cand-card">
  <h3 className="cand-title">{noCargo?'조회 결과를 찾지 못했어요':many?'같은 이름의 배가 여러 척 있어요':'배를 확인하고, 정확하게 판단할게요.'}</h3>
  {r.answer&&!noCargo&&<p className="cand-sub">{r.answer}</p>}
  <form onSubmit={submit}>
   <fieldset className="candidate-list cand-list" disabled={busy}><legend className="sr-only">선박 후보와 식별 근거</legend>
    {r.vessel_candidates.length?r.vessel_candidates.map(c=><label className={`candidate cand-row ${selected===c.mmsi?'selected':''}`} key={c.mmsi}>
     <input type="radio" name="vessel" value={c.mmsi} checked={selected===c.mmsi} onChange={()=>setSelected(c.mmsi)}/>
     <span className="cand-body">
      <strong>{c.name}</strong>
      <span className="cand-meta">{countryLabel(c.flag)} · {c.dest?portLabel(c.dest):'목적지 확인 안 됨'} · {dateTime(c.last_time,true)}</span>
      <span className="cand-ids">선박 식별 번호 <span className="mono">{c.mmsi}</span> · IMO 번호 {c.imo?<span className="mono">{c.imo}</span>:'확인 안 됨'} · {shipTypeLabel(c.ship_type)}</span>
      <span className="cand-why">후보로 본 이유: {c.match_reasons.join(' ')||'식별 근거가 없어요.'}</span>
     </span>
     <span className="cand-pick" aria-hidden="true">{selected===c.mmsi?<><Check size={16} strokeWidth={2}/>선택됨</>:'선택'}</span>
    </label>):noCargo?<p className="muted">{triedBoth?'하우스·마스터로 모두 조회했지만 결과가 없어요. B/L 번호를 다시 확인해 주세요.':'B/L 번호를 확인하고, 마스터·하우스 구분을 바꿔 다시 조회해 보세요.'}</p>:<p className="muted">고를 수 있는 선박이 없어요. 아래에서 필요한 정보를 입력해 주세요.</p>}
   </fieldset>
   {needsExtra&&<div className="cand-extra">
    {r.missing_inputs.includes('voyage_no')&&<div className="form-field"><label htmlFor="voyage">항차 번호</label><input id="voyage" value={voyage} onChange={e=>setVoyage(e.target.value)} disabled={busy} placeholder="도착 통지서의 항차 번호"/></div>}
    {r.missing_inputs.includes('forwarder_eta')&&<div className="form-field"><label htmlFor="forwarder">포워더가 알려 준 입항 예정일</label><input type="date" id="forwarder" value={eta} onChange={e=>setEta(e.target.value)} disabled={busy}/></div>}
    {r.missing_inputs.includes('bl_type')&&<div className="form-field"><label htmlFor="resolve-type">B/L 구분 다시 확인</label><select id="resolve-type" value={type} onChange={e=>setType(e.target.value as AgentRequest['bl_type'])}><option value="MASTER">마스터 B/L (선사가 발행)</option><option value="HOUSE">하우스 B/L (포워더가 발행)</option></select><small className="help-text">B/L은 선하증권이에요. 포워더에게 받은 서류라면 보통 하우스 B/L이에요.</small></div>}
    {r.missing_inputs.filter(x=>!known.includes(x)).map(x=><p key={x} className="cand-more">추가 정보가 더 필요해요. 포워더에게 확인해 주세요.</p>)}
   </div>}
   {error&&<p role="alert" className="field-error">{error}</p>}
   {!triedBoth&&<div className="cand-actions"><button className="button primary" disabled={busy}>확인하고 판정하기 <ArrowRight size={16} strokeWidth={2}/></button></div>}
   {docHints&&<small className="demo-caption">서류 사진에서 확인한 값을 채워 두었어요.</small>}
   {!isLive&&<small className="demo-caption">체험 모드: 첫 후보를 고르거나 추가 정보를 입력하면 예시 결과로 이어져요.</small>}
  </form>
 </section>;
}
