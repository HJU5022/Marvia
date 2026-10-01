'use client';
/** 내 화물 화면. 위는 문장 입력창(ChatBar, docs/specs/chat-search.md), 아래는 답의 종류별 결과(화물 카드 / 입항 선박 표).
 * status 5종을 모두 분기하고, 카드는 응답 필드만 보고 그린다 (SDD 5.13).
 * 데모 모드는 첫 화면에 정상 예시를 자동으로 보여 주고, 실제 모드는 입력을 기다린다. */
import {useEffect,useRef,useState} from 'react';
import {ArrowDown,ArrowUpRight,Check,FilterX,Ship} from 'lucide-react';
import {ChatBar} from '@/components/ChatBar';
import {VesselList} from '@/components/VesselList';
import {useApp} from '@/components/AppProvider';
import {VerdictCard} from '@/components/VerdictCard';
import {VesselCard} from '@/components/VesselCard';
import {EtaCompare} from '@/components/EtaCompare';
import {MapPanel} from '@/components/MapPanel';
import {CustomsTimeline} from '@/components/CustomsTimeline';
import {EvidenceCards} from '@/components/EvidenceCards';
import {CandidatePicker} from '@/components/CandidatePicker';
import {FailureBanner} from '@/components/FailureBanner';
import {isLive,selectFixture} from '@/lib/api';
import {dateTime,maskBl,statusLabels} from '@/lib/format';
import type {AgentRequest} from '@/lib/types';
export default function CargoPage(){
 // 로딩 원은 실제로 기다리는 중일 때만 돈다. 실제 모드의 첫 화면은 입력 대기라 멈춘 아이콘을 보여 준다
 const {data,lookup,request,result:r,loading,error,replaying,view,vessels}=useApp();const started=useRef(false);const [mofOnly,setMofOnly]=useState(false);
 useEffect(()=>{if(started.current)return;started.current=true;if(r||isLive)return;const id=process.env.NODE_ENV==='development'?new URLSearchParams(window.location.search).get('fixture'):null;const choice=data.demo.choices.find(c=>c.id===id)??data.demo.choices[0];selectFixture(id);void lookup(choice.request as AgentRequest);},[data,lookup,r]);
 useEffect(()=>{setMofOnly(false);},[r]);
 function showMof(){setMofOnly(true);setTimeout(()=>document.getElementById('evidence')?.scrollIntoView({behavior:'smooth',block:'start'}),20);}
 return <div className="page cargo-page"><div className="page-heading"><div><span className="eyebrow">CARGO INTELLIGENCE</span><h1>내 화물, 지금 어떤가요<span className="accent-dot">.</span></h1><p>도착 예정에서 끝나지 않는, 근거 있는 판단.</p></div><a href="#evidence" className="quiet-link">근거부터 살펴보기 <ArrowDown size={15}/></a></div><ChatBar/>{view==='vessels'&&vessels?<VesselList data={vessels}/>:r?<div className={loading?'result-content updating':'result-content'} aria-busy={loading} data-testid="result" data-status={r.status}><div className="result-meta"><div><span className="cargo-id mono">B/L {maskBl(request.bl_no)}</span><span className="meta-divider"/><span>{statusLabels[r.status]}</span>{replaying&&<span className="subtle-badge">이력 재생</span>}</div><span className="last-updated">{r.evidence[0]?`${dateTime(r.evidence[0].fetched_at,true)} 기준`:'조회 시각 미제공'}</span></div><FailureBanner response={r} onRetry={()=>void lookup({...request,follow_up_question:null})} busy={loading} onMof={showMof}/>{r.status==='insufficient'?<CandidatePicker key={r.trace_id} response={r} request={request} onResolve={req=>void lookup(req)} busy={loading}/>:<>{r.verdict&&<VerdictCard response={r} request={request}/>}<div className="cargo-body"><div className="cargo-primary"><MapPanel response={r}/><VesselCard response={r}/></div><div className="cargo-aside"><EtaCompare response={r}/><CustomsTimeline response={r}/></div></div></>}{r.reasons.length>0&&<section className="signal-summary" aria-label="판정 신호"><span>확인한 신호</span>{r.reasons.map((s,i)=><details key={i} className={s.triggered?'triggered':''}><summary><Check size={13}/>{s.rule}</summary><p>{s.value} · {s.triggered?'감지됨':'감지되지 않음'}</p></details>)}</section>}<div className="bottom-grid"><div>{mofOnly&&<div className="filter-notice">해수부 근거만 표시 중 · 새로운 판정이 아닙니다.<button onClick={()=>setMofOnly(false)}><FilterX size={14}/>전체 보기</button></div>}<EvidenceCards evidence={mofOnly?r.evidence.filter(e=>e.source==='mof'):r.evidence} traceId={r.trace_id}/></div></div></div>:<div className="initial-loading" role="status">{(loading||(!isLive&&!error))?<div className="loading-orbit"/>:<Ship size={34} strokeWidth={1.2} className="idle-ship"/>}<strong>{isLive?(loading?'확인하고 있어요.':'무엇이든 물어보세요.'):error?'예시 화물을 선택해 주세요.':'저장된 화물을 확인하고 있어요.'}</strong><p>{loading||!isLive?'선박을 식별하고, 위치와 입항 근거를 정리합니다.':'B/L 번호가 든 문장이면 화물을, "중국에서 오는 배"처럼 물으면 입항 예정 선박을 찾아 드립니다.'}</p></div>}<div className="page-end"><span>확실하지 않을 때는, 추측 대신 한 번 더 묻습니다.</span><a href="/about">Marvia의 판단 방식 <ArrowUpRight size={14}/></a></div></div>;
}
