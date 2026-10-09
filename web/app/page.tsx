'use client';
/** 내 화물 화면. 맨 위 가운데가 AI 입력창(ChatBar, docs/specs/chat-search.md)이고 아래에 답의 종류별 결과(화물 카드 / 입항 선박 표)가 펼쳐진다.
 * AI 입력이 제품의 주 기능이라 보조 패널로 밀어내지 않는다 (강사 피드백, 구현작업서 4절).
 * status 5종을 모두 분기하고, 카드는 응답 필드만 보고 그린다 (SDD 5.13). 판정은 서버 값 그대로다.
 * 결과 순서: 판정과 지금 할 일 → 지도·ETA 비교 → 통관·선박 식별 → 신호·근거 (구현작업서 4절 대화와 결과 4항).
 * 데모 모드는 첫 화면에 정상 예시를 자동으로 보여 주고(가공 데이터, 유료 호출 아님), 실제 모드는 입력을 기다린다.
 */
import {useEffect,useRef,useState} from 'react';
import {ArrowLeft,ArrowUpRight,Check,ChevronDown,CircleHelp,FileText,FilterX,Minus,PanelLeftOpen} from 'lucide-react';
import {ChatBar} from '@/components/ChatBar';
import {VesselList} from '@/components/VesselList';
import {useApp} from '@/components/AppProvider';
import {VerdictCard} from '@/components/VerdictCard';
import {WatchToggle} from '@/components/WatchToggle';
import {VesselCard} from '@/components/VesselCard';
import {EtaCompare} from '@/components/EtaCompare';
import {MapPanel} from '@/components/MapPanel';
import {CustomsTimeline} from '@/components/CustomsTimeline';
import {CustomsDetailTable} from '@/components/CustomsDetailTable';
import {EvidenceCards} from '@/components/EvidenceCards';
import {CandidatePicker} from '@/components/CandidatePicker';
import {FailureBanner} from '@/components/FailureBanner';
import {isLive,selectFixture} from '@/lib/api';
import {dateTime,maskBl,ruleLabels} from '@/lib/format';
import type {AgentRequest} from '@/lib/types';

export default function CargoPage(){
 const {data,lookup,request,result:r,loading,error,replaying,view,vessels,thread,backToCargo,cargoKey,usage,authEnabled,user,conversationsOn}=useApp();const started=useRef(false);const [mofOnly,setMofOnly]=useState(false);const [moreOpen,setMoreOpen]=useState(false);
 // 데모 모드만 첫 화면에 저장된 예시를 연다. ?fixture=는 개발 서버에서 상태별 화면을 확인하는 용도다 (scripts/verify.mjs)
 useEffect(()=>{if(started.current)return;started.current=true;if(r||isLive)return;const id=process.env.NODE_ENV==='development'?new URLSearchParams(window.location.search).get('fixture'):null;const choice=data.demo.choices.find(c=>c.id===id)??data.demo.choices[0];selectFixture(id);void lookup(choice.request as AgentRequest);},[data,lookup,r]);
 // 새 화물일 때만 해수부 근거 거르기를 푼다. 후속 질문 답이 와도 보던 상태를 유지한다 (F10)
 useEffect(()=>{setMofOnly(false);setMoreOpen(false);},[cargoKey]);
 // 근거는 "펼쳐 보기" 안에 있다. 먼저 펼친 뒤 근거 칸으로 내려간다
 function showMof(){setMofOnly(true);setMoreOpen(true);setTimeout(()=>document.getElementById('evidence')?.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'}),60);}
 const showing=view==='vessels'&&vessels?'vessels':view!=='none'&&r?'cargo':null;
 // 아무 결과도 없고 기다리지도 않을 때만 첫 화면 작업 카드를 보인다. 등록 화물 수 같은 API 없는 지표는 만들지 않는다
 const idle=!showing&&!loading;
 const failedLike=r?.status==='failed'||r?.status==='unsupported';
 // 하루 AI 사용량을 다 쓰면 다시 조회·후보 확정도 막는다. 서버도 429로 막는다 (docs/specs/token-quota.md, F7)
 const blocked=!!usage?.exhausted;
 // 화면 틀: 대화(왼쪽)와 상세(오른쪽). 결과가 없으면 대화만 가운데에 100:0, 결과가 생기면 40:60으로 나뉜다 (마누스 안A 화면1·2).
 // 사이드바 대화 목록 접기·화면 높이 맞추기는 Shell 바깥 CSS가 body 속성을 보고 한다 (styles/chat.css). 이 화면을 떠나면 속성을 걷는다.
 // 선박 표(vessels)는 열이 많아 상세 칸을 넓게 쓴다. 안내 답(view none)은 이전 화물을 숨겼다는 빈 칸과 돌아가기 버튼을 둔다 (시안 2-3)
 const split=!!showing||(!!r&&view==='none');
 const [sheetOpen,setSheetOpen]=useState(true);  // 휴대폰에서 상세 시트가 펼쳐졌는지. 새 화물이 오면 다시 펼친다
 useEffect(()=>{document.body.dataset.fit='1';return()=>{delete document.body.dataset.fit;delete document.body.dataset.split;};},[]);
 useEffect(()=>{if(split)document.body.dataset.split='1';else delete document.body.dataset.split;},[split]);
 useEffect(()=>{setSheetOpen(true);},[cargoKey]);
 // 채팅 칸의 지도 "크게 보기"가 접힌 시트를 먼저 올려 달라고 부탁한다 (ChatMiniMap)
 useEffect(()=>{const on=()=>setSheetOpen(true);window.addEventListener('marvia:sheet-open',on);return()=>window.removeEventListener('marvia:sheet-open',on);},[]);
 // 입력창을 누르면 휴대폰에서는 시트를 접어 키보드와 입력창이 가려지지 않게 한다
 const paneRef=useRef<HTMLElement>(null);
 useEffect(()=>{const el=paneRef.current;if(!el)return;const on=(e:FocusEvent)=>{if((e.target as HTMLElement).id==='chat-input')setSheetOpen(false);};el.addEventListener('focusin',on);return()=>el.removeEventListener('focusin',on);},[]);
 // 사이드바 대화 목록이 접힌 40:60에서 목록을 다시 연다. 목록 패널은 Shell이 갖고 있어 이벤트로 부탁한다 (Shell.tsx)
 const openConversations=()=>window.dispatchEvent(new Event('marvia:conversations'));
 const backButton=r&&showing!=='cargo'&&!loading?<button type="button" className="button secondary" onClick={backToCargo}><ArrowLeft size={15}/>내 화물 결과로 돌아가기<span className="mono">B/L {maskBl(request.bl_no)}</span></button>:null;
 return <div className={`chat-app${split?' split':''}${showing==='vessels'?' wide':''}${sheetOpen?' sheet-open':''}`}>
  <section className="chat-pane" ref={paneRef} aria-label="대화">
   <header className="pane-head">
    {conversationsOn&&<button type="button" className="pane-icon" aria-label="대화 목록 열기" onClick={openConversations}><PanelLeftOpen size={18}/></button>}
    {/* 보이는 "대화 내용" 제목을 없앴다. 화면 읽기 프로그램용 제목만 남긴다 */}
    <h1 className="sr-only">대화</h1>
   </header>
   {/* 지켜보던 화물의 판정이 바뀐 알림은 이제 대화의 첫 말풍선으로 온다 (AppProvider) */}
   {/* 데모 첫 조회처럼 대화 없이 실패한 경우만 여기 알린다. 문장 질문의 실패는 대화 칸에 이미 있다 */}
   {error&&!thread.length&&!showing&&<p role="alert" className="request-error page-error">{error}</p>}
   <ChatBar idle={idle} onShowDetail={()=>setSheetOpen(true)}/>
  </section>
  {split&&<section className="detail-pane" aria-label="화물 상세">
   {/* 휴대폰: 아래에서 올라오는 시트. 손잡이를 누르면 접고 편다. 넓은 화면에서는 보이지 않는다 */}
   <button type="button" className="sheet-handle" aria-expanded={sheetOpen} onClick={()=>setSheetOpen(o=>!o)}><span aria-hidden="true"/><strong>화물 상세 · {data.demo.port.name}</strong></button>
   <div className="detail-scroll">
    {/* 화물 결과가 숨겨졌거나 선박 표가 보일 때 돌아갈 길 (F4) */}
    {showing!=='cargo'&&<div className="detail-head">{!showing&&<h2>화물 결과</h2>}{backButton}</div>}
    {showing==='vessels'&&vessels&&<VesselList data={vessels}/>}
    {!showing&&<div className="detail-empty"><span aria-hidden="true"><FileText size={26}/></span><strong>이전 화물 결과는 잠시 숨겨져 있어요.</strong>{!backButton&&<p>다시 보려면 내 화물 결과로 돌아가세요.</p>}</div>}
   {/* key: 새 화물 조회일 때만 카드가 한 번 떠오른다. 후속 질문 답은 같은 key라 지도·펼친 근거를 다시 만들지 않는다 (구현작업서 5절, F10) */}
   {showing==='cargo'&&r&&<section key={cargoKey||r.trace_id} className={loading?'result updating':'result'} aria-busy={loading} aria-label="화물 조회 결과" data-testid="result" data-status={r.status}>
   {/* 다시 조회·후보 확정 중에는 지난 결과를 남겨 두되 새 결과가 아님을 밝힌다 (구현작업서 4절 8항) */}
   {loading&&<p className="stale-notice" role="status">이전 조회 결과예요 · 새 결과를 기다리고 있어요</p>}
   {error&&!loading&&<p role="alert" className="request-error">{error} 아래는 이전 조회 결과예요.</p>}
   {/* 머리 한 줄: B/L과 기준 시각만. 조회 상태는 아래 안내·판정이 이미 말하고, "체험 · 예시 데이터"는 상단바에 한 번만 둔다 */}
   <div className="result-head">
    <div className="result-id"><strong className="mono">B/L {maskBl(request.bl_no)}</strong>{replaying&&<span className="status-chip replay history">저장된 이력</span>}</div>
    {/* 근거가 없으면 시각을 비운다. "조회 시각을 알 수 없어요"는 결과 없음 화면에서 고장처럼 보였다 */}
    {r.evidence[0]&&<span className="last-updated">{dateTime(r.evidence[0].fetched_at,true)} 기준</span>}
   </div>
   <FailureBanner response={r} onRetry={()=>void lookup({...request,follow_up_question:null})} busy={loading||blocked} onMof={showMof}/>
   {r.status==='insufficient'?<CandidatePicker key={r.trace_id} response={r} request={request} onResolve={req=>void lookup(req)} busy={loading||blocked}/>
    :failedLike?<div className="unknown-note"><CircleHelp size={22}/><div><h2>확인하지 못한 값은 비워 뒀어요.</h2><p>판정·현재 위치·도착 예정일을 짐작해서 채우지 않아요. 확인된 근거만 아래에서 볼 수 있어요.</p></div></div>
    // 상세 패널 순서 (마누스 시안 2-2, 01_공통 "상세 패널"): 지도(+떠 있는 카드) → 판정 → 일정 줄 → 통관 → 펼쳐 보기
    :<>{/* 지켜보기 버튼은 지도 위 카드 안에 들어간다. 체험 모드·로그인이 꺼진 서버·비로그인에서는 그리지 않는다 */}
     <MapPanel response={r} watch={r.verdict&&isLive&&authEnabled&&!!user?<WatchToggle blNo={request.bl_no}/>:undefined}/>
     {r.verdict&&<VerdictCard response={r} request={request}/>}
     <EtaCompare response={r}/>
     <div className="detail-sub"><CustomsTimeline response={r}/></div></>}
   {/* 펼쳐 보기: 판정 근거 · 출처별 원본 자료 · 통관 이력. 실패·확인 필요 화면은 남은 근거를 바로 보게 처음부터 펼친다 */}
   {(()=>{const forceOpen=failedLike||r.status==='insufficient';const hasSignals=r.reasons.length>0&&!failedLike;const hasEvidence=r.evidence.length>0;const hasHistory=r.status!=='insufficient';
    const names=[hasSignals||hasEvidence?'판정 근거':null,!failedLike&&r.status!=='insufficient'?'출처별 원본 자료':null,hasHistory?(r.customs_detail?.length?'통관 이력 · 관세청 처리 내역':'통관 이력'):null].filter(Boolean);
    if(!names.length)return null;
    return <details className="more-fold" open={forceOpen||moreOpen} onToggle={e=>{if(!forceOpen)setMoreOpen(e.currentTarget.open);}}>
     {/* 상세 정보: 구역 제목 + 근거 개수 + 펼치기 버튼 모양. 지나가는 한 줄로 보여 상세인 줄 모른다는 지적 */}
     <summary><strong>상세 정보</strong>{r.evidence.length>0&&<em className="more-count">근거 {r.evidence.length}개</em>}<span className="more-action">{forceOpen||moreOpen?'접기':'펼쳐 보기'}<ChevronDown size={16} className="more-chevron" aria-hidden="true"/></span><span className="more-names">{names.join(' · ')}</span></summary>
     <div className="more-body">
      {(hasSignals||hasEvidence)&&<section className="more-block" aria-label="판정 근거">
       {r.answer&&!failedLike&&r.verdict&&<p className="answer-summary">{r.answer}</p>}
       {/* 체크 표시는 감지된 신호에만 단다. 감지 안 된 신호에 체크가 붙으면 "문제 있음"으로 읽혔다 (UI 점검 F8) */}
       {hasSignals&&<div className="signal-summary" aria-label="판정 신호"><span>확인한 신호</span>{r.reasons.map((s,i)=><details key={i} className={s.triggered?'triggered':'clear'}><summary>{s.triggered?<Check size={13} aria-hidden="true"/>:<Minus size={13} aria-hidden="true"/>}{ruleLabels[s.rule]??'기타 신호'}<span className="signal-state">{s.triggered?'해당됨':'해당 없음'}</span></summary><p>{s.value}</p></details>)}</div>}
       {hasEvidence&&<div>{mofOnly&&<div className="filter-notice">해수부 근거만 보여 드리는 중이에요 · 새 판정이 아니에요.<button onClick={()=>setMofOnly(false)}><FilterX size={14}/>전체 보기</button></div>}<EvidenceCards evidence={mofOnly?r.evidence.filter(e=>e.source==='mof'):r.evidence} traceId={r.trace_id}/></div>}
      </section>}
      {!failedLike&&r.status!=='insufficient'&&<section className="more-block" aria-label="출처별 원본 자료"><EtaCompare response={r} part="sources"/><VesselCard response={r}/></section>}
      {hasHistory&&<section className="more-block" aria-label="통관 이력"><CustomsTimeline response={r} part="history"/><CustomsDetailTable rows={r.customs_detail}/></section>}
     </div>
    </details>;})()}
  </section>}
    <div className="page-end"><span>확실하지 않으면 짐작하지 않고 한 번 더 물어봐요.</span><a href="/about">Marvia의 판단 방식 알아보기 <ArrowUpRight size={14}/></a></div>
   </div>
  </section>}
 </div>;
}
