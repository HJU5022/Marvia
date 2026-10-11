'use client';
/** 평가 지표 (운영자 전용). 실제 모드는 GET /api/metrics(evals/results의 실행 결과), 데모는 fixture.
 * 값이 없으면 0이 아니라 "측정 전" 한 곳으로만 보인다 (CLAUDE.md: 실행하지 않은 숫자를 만들지 않는다).
 * 엘레강스: 얇은 글씨, 2px 막대. 표·그래프·시각 요소 중심으로 다시 짬. 새 라이브러리 없이 CSS 막대와 인라인 SVG만 쓴다.
 * 통과·미달은 신호등 색이 아니라 아이콘+글자로 구분한다 (초록·노랑·빨강은 순항·주의·긴급 전용). */
import {useEffect,useState} from 'react';
import {ArrowUpRight,CircleCheck,CircleX,Hourglass} from 'lucide-react';
import {getMetrics} from '@/lib/api';
import {dateTime} from '@/lib/format';
import {useApp} from './AppProvider';

const num=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v);

/** KPI 합격선. 백엔드 게이트에 목표가 있는 두 지표만 선을 긋는다 (긴급 재현율 100%, 출력 계약 95%). 나머지는 선 없이 막대만 */
const PASS_LINE:Record<string,number>={act_recall:100,schema_pass:95};

/** 게이트 한 줄의 결과 표시. 통과/미달/대기를 아이콘 모양으로 가른다 */
function Mark({passed}:{passed:boolean|null|undefined}){
  const state=passed==null?'wait':passed?'pass':'fail';
  const Icon=state==='pass'?CircleCheck:state==='fail'?CircleX:Hourglass;
  return <span className={`mt-mark ${state}`}><Icon size={16} strokeWidth={1.5}/>{state==='pass'?'통과':state==='fail'?'미달':'-'}</span>;
}

/** KPI 막대: 0~100 길이 + 합격선 눈금. 값이 없으면 그리지 않는다 */
function KpiBar({value,line,label}:{value:number;line?:number;label:string}){
  return <span className="mt-kbar" role="img" aria-label={`${label} ${value}%${line!=null?`, 합격선 ${line}%`:''}`}>
    <i style={{width:`${Math.min(100,Math.max(0,value))}%`}}/>{line!=null&&<b style={{left:`${line}%`}}/>}</span>;
}

type Run={config:string;model:string|null;run_at:string|null;commit:string|null;exact_match:number|null;count:number|null;gate_passed:boolean|null;llm_calls:number|null;cost_usd:number|null;file:string};

/** 정답 일치율 꺾은선. 실행 기록을 오래된 것부터 시간순으로, 값이 있는 것만 잇는다 (없는 값은 만들지 않는다) */
function Spark({runs}:{runs:Run[]}){
  const pts=[...runs].reverse().filter(r=>num(r.exact_match)&&num(r.count)&&r.count>0)
    .map(r=>({r,v:(r.exact_match as number)/(r.count as number)*100}));
  if(pts.length<2) return null;
  const W=640,H=96,pad=8,lo=Math.min(...pts.map(p=>p.v),100)-5,hi=100;
  const x=(i:number)=>pad+i*(W-pad*2)/(pts.length-1);
  const y=(v:number)=>pad+(hi-v)/(hi-lo)*(H-pad*2);
  return <svg className="mt-spark" viewBox={`0 0 ${W} ${H}`} role="img" preserveAspectRatio="none"
    aria-label={`정답 일치율 추이, ${pts.length}번 실행, 최근 ${pts[pts.length-1].v.toFixed(1)}%`}>
    <line x1={pad} x2={W-pad} y1={y(100)} y2={y(100)} className="mt-spark-ref"/>
    <polyline points={pts.map((p,i)=>`${x(i)},${y(p.v)}`).join(' ')} className="mt-spark-line"/>
    {pts.map((p,i)=><circle key={p.r.file} cx={x(i)} cy={y(p.v)} r={3} className={`mt-spark-dot${p.r.gate_passed===false?' fail':''}`}/>)}
  </svg>;
}

export function MetricsPage(){
  const {data}=useApp();
  const [live,setLive]=useState<typeof data.metrics|null>(null);
  useEffect(()=>{void getMetrics().then(setLive);},[]);
  const m=live??data.metrics;
  const runs=(m.experiments??[]) as unknown as Run[];
  const datasetSize=(m as {dataset_size?:number|null}).dataset_size;
  const measured=m.kpis.some(k=>num(k.value))||m.comparison.some(r=>[r.baseline,r.model_a,r.model_b].some(num))||runs.length>0;
  const state=m.gate_passed==null?'wait':m.gate_passed?'pass':'fail';

  return <div className="page mt-page">
    <div className="page-heading adm-heading"><div><span className="eyebrow">운영자</span><h1>평가 지표</h1></div></div>

    {!measured?<p className="mt-empty">측정 전</p>:<>
    <p className="mt-status"><span className={`mt-dot ${state}`}/>{state==='pass'?'합격 기준 통과':state==='fail'?'합격 기준 미달':'측정 대기'}
      {m.updated_at&&<small>골든셋 {datasetSize?`${datasetSize}건 `:''}평가 결과 · 서비스 구성(b) · 마지막 실행 {dateTime(m.updated_at as unknown as string)} 기준 (실시간 아님)</small>}</p>

    <div className="mt-kpis">{m.kpis.map(k=>{
      const line=PASS_LINE[k.id];
      return <div key={k.id} className="mt-kpi"><h2>{k.label}</h2>
        {num(k.value)?<><strong>{k.value}<span>{k.unit}</span></strong><KpiBar value={k.value} line={line} label={k.label}/>
          <small>{line!=null?`합격선 ${line}%`:' '}</small></>
        :<><strong className="none">-</strong><span className="mt-kbar empty"/><small>&nbsp;</small></>}</div>;})}</div>

    <section className="mt-section">
      <div className="mt-head"><h2>구성별 비교</h2><span className="mt-legend"><i className="a"/>기준선 (a)<i className="b"/>서비스 (b)<i className="c"/>비교 모델 (c)</span></div>
      <ul className="mt-chart">{m.comparison.map(row=>{
        const vals=[['기준선 (a)',row.baseline,'a'],['서비스 (b)',row.model_a,'b'],['비교 모델 (c)',row.model_b,'c']] as const;
        return <li key={row.id}><span className="mt-chart-label">{row.label}</span>
          <div className="mt-chart-bars">{vals.map(([name,v,tone])=>
            <div key={tone} className="mt-chart-row">
              <span className={`mt-bar ${tone}`} role="img" aria-label={num(v)?`${row.label} ${name} ${v}%`:`${row.label} ${name} 측정 전`}>{num(v)&&<i style={{width:`${Math.min(100,Math.max(0,v))}%`}}/>}</span>
              <span className="mt-chart-val">{num(v)?`${v}%`:'-'}</span></div>)}</div></li>;})}</ul>
    </section>

    <div className="mt-bottom">
      <section className="mt-section">
        <div className="mt-head"><h2>합격 기준</h2></div>
        <div className="table-scroll"><table className="mt-table"><thead><tr><th>항목</th><th>기준</th><th>결과</th><th/></tr></thead>
          <tbody>{m.gates.map((g,i)=><tr key={i}><td>{g.label}</td><td>{g.target??'-'}</td><td>{g.value??'-'}</td>
            <td>{g.passed!=null?<Mark passed={g.passed}/>:null}</td></tr>)}</tbody></table></div>
      </section>
      <section className="mt-section">
        <div className="mt-head"><h2>평가 기록</h2>{runs.length>0&&<span className="mt-legend">{runs.length}건</span>}</div>
        {runs.length?<>
          <Spark runs={runs}/>
          <div className="table-scroll"><table className="mt-table"><thead><tr><th>일시</th><th>구성</th><th>모델</th><th>일치</th><th/></tr></thead>
            <tbody>{runs.map((r,i)=><tr key={r.file??i}>
              <td>{r.run_at?dateTime(r.run_at):'-'}</td><td>({r.config})</td><td>{r.model??'-'}</td>
              <td>{r.exact_match==null?'-':`${r.exact_match}/${r.count}`}</td><td><Mark passed={r.gate_passed}/></td></tr>)}</tbody></table></div></>
        :<p className="mt-empty sm">측정 전</p>}
      </section>
    </div></>}
    <a className="quiet-link" href="/about">Marvia의 평가 방식 알아보기 <ArrowUpRight size={16}/></a>
  </div>;
}
