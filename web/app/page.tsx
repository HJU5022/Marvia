'use client';
/** 내 화물 화면. 맨 위 가운데가 AI 입력창(ChatBar, docs/specs/chat-search.md)이고 아래에 답의 종류별 결과(화물 카드 / 입항 선박 표)가 펼쳐진다.
 * AI 입력이 제품의 주 기능이라 보조 패널로 밀어내지 않는다 (강사 피드백, 구현작업서 4절).
 * status 5종을 모두 분기하고, 카드는 응답 필드만 보고 그린다 (SDD 5.13). 판정은 서버 값 그대로다.
 * 결과 순서: 판정과 지금 할 일 → 지도·ETA 비교 → 통관·선박 식별 → 신호·근거 (구현작업서 4절 대화와 결과 4항).
 * 데모 모드는 첫 화면에 정상 예시를 자동으로 보여 주고(가공 데이터, 유료 호출 아님), 실제 모드는 입력을 기다린다.
 */
import {useEffect,useRef,useState} from 'react';
import {ArrowUpRight,Check,CircleHelp,FilterX,Sparkles} from 'lucide-react';
import {ChatBar} from '@/components/ChatBar';
import {VesselList} from '@/components/VesselList';
import {useApp} from '@/components/AppProvider';
import {VerdictCard} from '@/components/VerdictCard';
import {WatchToggle} from '@/components/WatchToggle';
import {VesselCard} from '@/components/VesselCard';
import {EtaCompare} from '@/components/EtaCompare';
import {MapPanel} from '@/components/MapPanel';
import {CustomsTimeline} from '@/components/CustomsTimeline';
import {EvidenceCards} from '@/components/EvidenceCards';
import {CandidatePicker} from '@/components/CandidatePicker';
import {FailureBanner} from '@/components/FailureBanner';
import {isLive,selectFixture} from '@/lib/api';
import {dateTime,maskBl,ruleLabels,statusLabels} from '@/lib/format';
import type {AgentRequest} from '@/lib/types';

export default function CargoPage(){
 const {data,lookup,request,result:r,loading,error,replaying,view,vessels,thread,authEnabled,user}=useApp();const started=useRef(false);const [mofOnly,setMofOnly]=useState(false);
 // 데모 모드만 첫 화면에 저장된 예시를 연다. ?fixture=는 개발 서버에서 상태별 화면을 확인하는 용도다 (scripts/verify.mjs)
 useEffect(()=>{if(started.current)return;started.current=true;if(r||isLive)return;const id=process.env.NODE_ENV==='development'?new URLSearchParams(window.location.search).get('fixture'):null;const choice=data.demo.choices.find(c=>c.id===id)??data.demo.choices[0];selectFixture(id);void lookup(choice.request as AgentRequest);},[data,lookup,r]);
 useEffect(()=>{setMofOnly(false);},[r]);
 function showMof(){setMofOnly(true);setTimeout(()=>document.getElementById('evidence')?.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'}),20);}
 const showing=view==='vessels'&&vessels?'vessels':view!=='none'&&r?'cargo':null;
 // 아무 결과도 없고 기다리지도 않을 때만 첫 화면 작업 카드를 보인다. 등록 화물 수 같은 API 없는 지표는 만들지 않는다
 const idle=!showing&&!loading;
 const failedLike=r?.status==='failed'||r?.status==='unsupported';
 return <div className="page cargo-page">
  <section className="hero" aria-labelledby="hero-title">
   <span className="ai-label"><Sparkles size={13}/>YOUR CARGO COPILOT</span>
   <h1 id="hero-title">내 화물의 다음 한 걸음,<br/><span>Marvia에게 물어보세요.</span></h1>
   <p>B/L 조회부터 입항 선박 검색까지. 질문 하나로, 근거까지 명확하게.</p>
   <ChatBar idle={idle}/>
  </section>
  {/* 지켜보던 화물의 판정이 바뀐 알림은 이제 대화의 첫 말풍선으로 온다 (AppProvider, 10-06 결정) */}
  {/* 데모 첫 조회처럼 대화 없이 실패한 경우만 여기 알린다. 문장 질문의 실패는 대화 칸에 이미 있다 */}
  {error&&!thread.length&&!showing&&<p role="alert" className="request-error page-error">{error}</p>}
  {showing==='vessels'&&vessels&&<VesselList data={vessels}/>}
  {/* key: 새 결과(trace_id)일 때만 카드가 한 번 떠오른다. 같은 결과를 다시 그릴 때는 움직이지 않는다 (구현작업서 5절) */}
  {showing==='cargo'&&r&&<section key={r.trace_id} className={loading?'result updating':'result'} aria-busy={loading} aria-label="화물 조회 결과" data-testid="result" data-status={r.status}>
   {/* 다시 조회·후보 확정 중에는 지난 결과를 남겨 두되 새 결과가 아님을 밝힌다 (구현작업서 4절 8항) */}
   {loading&&<p className="stale-notice" role="status">이전 조회 결과입니다 · 새 결과를 기다리는 중</p>}
   {error&&!loading&&<p role="alert" className="request-error">{error} 아래는 이전 조회 결과입니다.</p>}
   <div className="result-head">
    <div className="result-id"><strong className="mono">B/L {maskBl(request.bl_no)}</strong><span className={`status-chip ${r.status}`}>{statusLabels[r.status]}</span>{replaying&&<span className="status-chip replay">이력 재생</span>}{!isLive&&<span className="status-chip replay">재생 · 가공 데이터</span>}</div>
    <span className="last-updated">{r.evidence[0]?`${dateTime(r.evidence[0].fetched_at,true)} 기준`:'조회 시각 미제공'}</span>
   </div>
   <FailureBanner response={r} onRetry={()=>void lookup({...request,follow_up_question:null})} busy={loading} onMof={showMof}/>
   {r.status==='insufficient'?<CandidatePicker key={r.trace_id} response={r} request={request} onResolve={req=>void lookup(req)} busy={loading}/>
    :failedLike?<div className="unknown-note"><CircleHelp size={22}/><div><h2>확인하지 못한 값은 비워 둡니다.</h2><p>판정·현재 위치·도착 예정일을 추정해서 채우지 않습니다. 응답에 남은 근거만 아래에서 확인하세요.</p></div></div>
    :<>{r.verdict&&<VerdictCard response={r} request={request}/>}
     {r.verdict&&isLive&&authEnabled&&!!user&&<WatchToggle blNo={request.bl_no}/>}
     <div className="result-grid"><MapPanel response={r}/><EtaCompare response={r}/></div>
     <div className="result-subgrid"><CustomsTimeline response={r}/><VesselCard response={r}/></div></>}
   {r.reasons.length>0&&!failedLike&&<section className="signal-summary" aria-label="판정 신호"><span>확인한 신호</span>{r.reasons.map((s,i)=><details key={i} className={s.triggered?'triggered':''}><summary><Check size={13}/>{ruleLabels[s.rule]??'기타 신호'}</summary><p>{s.value} · {s.triggered?'감지됨':'감지되지 않음'}</p></details>)}</section>}
   {r.evidence.length>0&&<div>{mofOnly&&<div className="filter-notice">해수부 근거만 표시 중 · 새로운 판정이 아닙니다.<button onClick={()=>setMofOnly(false)}><FilterX size={14}/>전체 보기</button></div>}<EvidenceCards evidence={mofOnly?r.evidence.filter(e=>e.source==='mof'):r.evidence} traceId={r.trace_id}/></div>}
  </section>}
  <div className="page-end"><span>확실하지 않을 때는, 추측 대신 한 번 더 묻습니다.</span><a href="/about">Marvia의 판단 방식 <ArrowUpRight size={14}/></a></div>
 </div>;
}
