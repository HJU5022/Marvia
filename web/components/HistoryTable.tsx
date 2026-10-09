'use client';
/** 조회 이력 (A12 요약 필드). 맨 위에 판정 분포 막대 하나와 그 범례(누르면 그 판정만 거른다), 아래에 한 줄이 한 건인 조용한 목록.
 * 한 건 = B/L과 한 줄 메모(시각·처리 상태·배 일치·판정 방식)와 오른쪽 판정 배지. 서버가 보내는 것은 요약뿐이라(판정·상태·배 일치·판정 방식)
 * 근거 문장은 지어내지 않는다 (맨 아래 안내 줄은 뺐다).
 * 오프라인(데모) 스냅샷은 GET /history 응답과 달라서 행 끝의 열기 아이콘 버튼으로만 다시 불러온다. */
import {useEffect,useState} from 'react';
import {useRouter} from 'next/navigation';
import {ArrowUpRight,History,Search} from 'lucide-react';
import {getHistory,isLive} from '@/lib/api';
import {dateTime,statusLabels,verdictLabels} from '@/lib/format';
import type {HistoryResponse,Status,Verdict} from '@/lib/types';
import {useApp} from './AppProvider';
import {VerdictBadge} from './Shared';

/** 판정 방식: 서버가 알려 준 값만 말한다. 모르면 줄표 */
const DECIDED_BY: Record<string, string> = {rule: '규칙으로 판정', llm: 'AI로 판정'};
/** 막대와 범례 순서. null은 판정 없음 */
const GRADES = ['fine','watch','act',null] as const;

/** 검색어가 가린 B/L(bl_masked)에 맞는지 본다. 서버는 원본을 주지 않고 가운데 절반을 *로 가린 값만 준다 (SDD 3.5, schemas/customs.py mask_bl).
 * 그래서 가린 자리(*)는 어떤 글자와도 맞는 자리로 보고, 보이는 글자끼리는 같아야 한다. 원본 전체를 넣어도, 앞이나 뒤 일부만 넣어도 찾아진다.
 * 보이는 글자가 하나도 겹치지 않으면(검색어가 * 자리에만 놓이면) 아무 검색어나 맞게 되므로 맞지 않은 것으로 본다. */
function blMatches(masked:string,q:string){
 if(!q)return true;
 for(let i=0;i+q.length<=masked.length;i++){
  let ok=true,seen=false;
  for(let j=0;j<q.length;j++){const m=masked[i+j],c=q[j];if(m==='*'||c==='*')continue;if(m!==c){ok=false;break;}seen=true;}
  if(ok&&seen)return true;
 }
 return false;
}

export function HistoryTable(){
 const {data,replay,loading}=useApp();const router=useRouter();const [history,setHistory]=useState<HistoryResponse|null>(null);const [error,setError]=useState(''),[query,setQuery]=useState(''),[verdict,setVerdict]=useState(''),[status,setStatus]=useState(''),[period,setPeriod]=useState('all');
 // 기간을 고르면 실제 모드는 서버에 since를 보내 그 기간만 읽는다 (M3). 데모는 아래 화면 거름만 쓴다
 useEffect(()=>{let active=true;const since=isLive&&period!=='all'?new Date(Date.now()-Number(period)*86400000).toISOString():undefined;getHistory(undefined,since).then(v=>{if(active)setHistory(v);}).catch(()=>{if(active)setError('이력을 불러오지 못했어요.');});return()=>{active=false;};},[data.demo.session_id,period]);
 // 검색은 대소문자를 가리지 않는다. 결과 화면 머리의 B/L은 소문자로 입력해도 대문자로 보인다 (UI 점검 F15). 원본 B/L을 넣어도 가린 값과 맞춰 찾는다 (blMatches)
 const q=query.replace(/\s/g,'').toUpperCase();
 const rows=(history?.items??[]).filter(r=>blMatches((r.bl_masked??'').toUpperCase(),q)&&(!status||r.status===status)&&(!verdict||(verdict==='none'?!r.verdict:r.verdict===verdict))&&(period==='all'||((isLive?Date.now():new Date(data.demo.reference_time).valueOf())-new Date(r.created_at).valueOf())<=Number(period)*86400000));
 function open(id:string|null){if(!id||!replay(id)){setError(isLive?'지난 조회는 요약만 보관해요. 자세히 보려면 같은 B/L로 다시 조회해 주세요.':'이 항목은 자세한 내용이 저장되어 있지 않아요.');return;}router.push('/');}
 const all=history?.items??[];
 const counts=GRADES.map(v=>all.filter(r=>(r.verdict&&r.verdict in verdictLabels?r.verdict:null)===v).length);
 const total=counts.reduce((x,y)=>x+y,0);
 return <div className="hist">
  <div className="hist-bar">
   {/* 판정 분포: 글자(범례의 건수)가 같은 정보를 모두 담고, 막대는 한눈에 보는 그림이라 role=img로 한 문장 요약을 준다 */}
   <div className="hist-dist" role="img" aria-label={total?`판정 분포: ${GRADES.map((v,i)=>`${v?verdictLabels[v]:'판정 없음'} ${counts[i]}건`).join(', ')}`:'조회 이력 없음'}>
    {GRADES.map((v,i)=>counts[i]>0&&<span key={v??'none'} className={`seg ${v??'neutral'}`} style={{flexGrow:counts[i]}}/>)}
   </div>
   <div className="hist-legend" role="group" aria-label="판정별로 거르기">{GRADES.map((v,i)=><button key={v??'none'} type="button" aria-pressed={verdict===(v??'none')} title={`${v?verdictLabels[v]:'판정 없음'}만 보기`} className={`hist-stat ${v??'neutral'}${verdict===(v??'none')?' selected':''}`} onClick={()=>setVerdict(verdict===(v??'none')?'':v??'none')}><i aria-hidden="true"/><span>{v?verdictLabels[v]:'판정 없음'}</span><strong>{history?counts[i]:'-'}<small>건</small></strong></button>)}</div>
   <div className="hist-tools"><label className="hist-search"><Search size={18}/><input aria-label="B/L 번호 검색" value={query} onChange={e=>setQuery(e.target.value)} placeholder="B/L 번호 검색"/></label><select aria-label="조회 기간" value={period} onChange={e=>setPeriod(e.target.value)}><option value="all">전체 기간</option><option value="7">최근 7일</option><option value="30">최근 30일</option></select><select aria-label="판정별로 보기" value={verdict} onChange={e=>setVerdict(e.target.value)}><option value="">모든 판정</option>{Object.entries(verdictLabels).map(([k,v])=><option key={k} value={k}>{v}</option>)}<option value="none">판정 없음</option></select><select aria-label="상태별로 거르기" value={status} onChange={e=>setStatus(e.target.value)}><option value="">모든 상태</option>{Object.entries(statusLabels).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></div>
  </div>
  {error&&<p role="alert" className="request-error">{error}</p>}
  {!history?<div className="hist-skel" aria-busy="true" aria-label="이력을 불러오고 있어요."><i/><i/><i/><i/></div>
  :!history.available?<div className="hist-empty"><History size={28}/><h2>이력을 불러올 수 없어요.</h2><p>연결 상태를 확인한 뒤 다시 시도해 주세요.</p></div>
  :<>
   <p className="hist-count">{rows.length}건 표시, 최신순{isLive?', 최근 20건':''}</p>
   <ul className="hist-list" aria-label="조회 이력">{rows.map((r,i)=>{
    const v=r.verdict&&r.verdict in verdictLabels?r.verdict as Verdict:null;
    // 보조 정보는 한 줄로 합친다. 모르는 칸은 말하지 않는다
    const meta=[dateTime(r.created_at,true),statusLabels[r.status as Status]??r.status??'미확인',r.vessel_match==='confirmed'?'배 확인됨':r.vessel_match==='uncertain'?'배 확인 필요':'배 찾지 못함',r.decided_by?DECIDED_BY[r.decided_by]:null].filter(Boolean).join(' · ');
    return <li key={r.request_id??i} className="hist-item">
     <div className="hist-main">
      <strong className="mono hist-bl">{r.bl_masked??'확인 안 됨'}</strong>
      <p className="hist-meta">{meta}</p>
      {r.reason&&<p className="hist-reason">{r.reason}</p>}
     </div>
     <VerdictBadge verdict={v}/>
     {!isLive&&<button type="button" className="icon-btn open-record" title="저장된 판정 열기" onClick={()=>open(r.request_id)} disabled={loading} aria-label={`${r.bl_masked??'화물'} 저장된 판정 열기`}><ArrowUpRight size={18}/></button>}
    </li>;})}</ul>
   {!rows.length&&<div className="hist-empty"><Search size={28}/><h2>조건에 맞는 이력이 없어요.</h2><button className="button secondary" onClick={()=>{setQuery('');setStatus('');setVerdict('');setPeriod('all');}}>조건 초기화</button></div>}
  </>}
 </div>;
}
