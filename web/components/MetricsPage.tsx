'use client';
/** 평가 지표 (운영자 전용). 실제 모드는 GET /api/metrics(evals/results의 실행 결과), 데모는 fixture.
 * 값이 없으면 0이 아니라 미측정으로 보인다 (CLAUDE.md: 실행하지 않은 숫자를 만들지 않는다).
 * 게이트 통과·미통과는 신호등 색이 아니라 아이콘+글자로 구분한다 (초록·노랑·빨강은 순항·주의·긴급 전용, 10-06 결정). */
import {useEffect,useState} from 'react';
import {ArrowUpRight,CircleCheck,CircleX,FlaskConical,Hourglass,Info} from 'lucide-react';
import {getMetrics} from '@/lib/api';
import {dateTime} from '@/lib/format';
import {useApp} from './AppProvider';

/** 게이트 결과 칩. 통과/걸림/대기를 아이콘 모양과 굵기로 가른다 */
function GateChip({passed,passText,failText,waitText,large}:{passed:boolean|null|undefined;passText:string;failText:string;waitText:string;large?:boolean}){
  const state=passed==null?'wait':passed?'pass':'fail';
  const Icon=state==='pass'?CircleCheck:state==='fail'?CircleX:Hourglass;
  return <span className={`mx-gate ${state}${large?' lg':''}`}><Icon size={large?22:16}/>{state==='pass'?passText:state==='fail'?failText:waitText}</span>;
}

/** 가는 막대 하나. 값이 없으면(null) 비운 채 "측정 전", 숫자는 0~100으로 잘라 그린다. 막대는 글자 값을 돕는 그림이라 값 글자는 항상 같이 보인다
 * (role="img" + aria-label로 읽히게). 없는 숫자를 만들어 채우지 않는다 */
function Bar({value,label,tone}:{value:number|null|undefined;label:string;tone?:'a'|'b'|'c'}){
  const has=typeof value==='number'&&Number.isFinite(value);
  const pct=has?Math.min(100,Math.max(0,value)):0;
  return <span className={`mx-bar${tone?` ${tone}`:''}`} role="img" aria-label={has?`${label} ${value}%`:`${label} 측정 전`}><i style={{width:`${pct}%`}}/></span>;
}
function Val({value}:{value:number|null|undefined}){
  return typeof value==='number'?<span className="mx-val">{value}<small>%</small></span>:<span className="mx-val none">측정 전</span>;
}

/** 비교표 항목 옆 ⓘ. 재료(4차 A-51)에 뜻이 있는 항목만 단다. 누르면 아래에 한 줄 설명 */
const TERM_HELP: Record<string, string> = {grounded: '설명이 근거와 일치한 비율'};

export function MetricsPage(){
  const {data}=useApp();
  const [live,setLive]=useState<typeof data.metrics|null>(null);
  const [help,setHelp]=useState<string|null>(null);
  useEffect(()=>{void getMetrics().then(setLive);},[]);
  const m=live??data.metrics;
  const runs=(m.experiments??[]) as Array<Record<string,unknown>>;
  const datasetSize=(m as {dataset_size?:number|null}).dataset_size;
  // 시안 4-8의 열 이름. 서버 필드 baseline=기준선(a), model_a=서비스(b), model_b=비교 모델(c)
  return <div className="page mx-page">
    <div className="page-heading adm-heading">
      <div><span className="eyebrow">운영자</span><h1>평가 지표</h1><p>서비스 구성(b)의 평가 결과와 합격 기준을 확인해요.</p></div>
    </div>

    <div className="mx-banner">
      <h2 className="mx-banner-state"><GateChip large passed={m.gate_passed} passText="합격 기준 통과" failText="합격 기준 미달" waitText="측정 대기"/></h2>
      <p>{m.updated_at?`서비스 구성(b) · ${dateTime(m.updated_at as unknown as string)}${datasetSize?` · 평가 문항 ${datasetSize}개`:''}`:'실제 평가 결과가 연결되면 여기에 표시돼요. 지금은 아직 측정하지 않았어요.'}</p>
    </div>

    <div className="mx-kpis">{m.kpis.map(k=>
      <div key={k.id} className="mx-kpi"><h2>{k.label}</h2>
        <strong>{k.value===null?<span className="mx-none">측정 전</span>:<>{k.value}<span>{k.unit}</span></>}</strong>
        <Bar value={k.value as number|null} label={k.label} tone="b"/></div>)}</div>

    <section className="mx-section">
      <div className="mx-card-head"><h2>구성별 비교</h2><span className="mx-legend"><i className="mx-key a"/>기준선(a)<i className="mx-key b"/>서비스(b)<i className="mx-key c"/>비교(c)</span></div>
      <div className="table-scroll mx-table" role="region" aria-label="평가 비교 표" tabIndex={0}><table>
        <thead><tr><th>평가 항목</th><th>기준선 (a)</th><th className="mx-service">서비스 (b)</th><th>비교 모델 (c)</th></tr></thead>
        <tbody>{m.comparison.map(row=>
          <tr key={row.id}><td data-label="평가 항목">{row.label}{TERM_HELP[row.id]&&<button type="button" className="mx-info" aria-label={`${row.label} 설명`} title={TERM_HELP[row.id]} aria-expanded={help===row.id} onClick={()=>setHelp(h=>h===row.id?null:row.id)}><Info size={16}/></button>}
              {help===row.id&&<small className="mx-help">{TERM_HELP[row.id]}</small>}</td>
            {([['기준선 (a)',row.baseline,'a'],['서비스 (b)',row.model_a,'b'],['비교 모델 (c)',row.model_b,'c']] as const).map(([name,v,tone])=>
              <td key={tone} className={tone==='b'?'mx-service':''} data-label={name}><Val value={v as number|null}/><Bar value={v as number|null} label={`${row.label} ${name}`} tone={tone}/></td>)}</tr>)}</tbody>
      </table></div>
    </section>

    <div className="mx-bottom">
      <section className="mx-section">
        <div className="mx-card-head"><h2>합격 기준</h2></div>
        <ul className="mx-gates">{m.gates.map((g,i)=>
          <li key={i}><span>{g.label}</span><small>{g.target??'-'}</small><strong>{g.value??'측정 대기'}</strong>
            {g.passed!=null?<GateChip passed={g.passed} passText="통과" failText="미달" waitText="-"/>:<span className="mx-gate-slot" aria-hidden="true"/>}</li>)}</ul>
      </section>
      <section className="mx-section">
        <div className="mx-card-head"><h2>최근 평가 기록</h2>{runs.length>0&&<span className="mx-legend">{runs.length}건</span>}</div>
        {runs.length?<ol className="mx-runs">{runs.map((r,i)=>
          <li key={String(r.file??i)}>
            <span className="mx-config">({String(r.config)})</span>
            <div><strong>{String(r.model??'-')}</strong>
              <small>{dateTime(r.run_at as string)} · {String(r.commit??'').slice(0,12)} · {r.exact_match==null?'-':`${r.exact_match}/${r.count}`}</small></div>
            <GateChip passed={r.gate_passed as boolean|null|undefined} passText="합격 기준 통과" failText="합격 기준 미달" waitText="합격 기준 -"/>
          </li>)}</ol>
        :<div className="mx-empty"><FlaskConical size={28} strokeWidth={1.5}/><h3>기록된 실험이 없어요.</h3></div>}
        {!live&&<p className="mx-note">체험용 예시 값이에요. 운영 서버에 연결하면 실제 평가 결과로 바뀌어요.</p>}
      </section>
    </div>
    <a className="quiet-link" href="/about">Marvia의 평가 방식 알아보기 <ArrowUpRight size={16}/></a>
  </div>;
}
