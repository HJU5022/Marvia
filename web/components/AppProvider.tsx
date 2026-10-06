'use client';
/** 화면 전체가 같이 쓰는 상태: 마지막 요청·응답, 로그인 사용자, 서류 사진에서 확인한 값 (SDD 4.3, E3, E9, G3).
 * 응답은 받은 그대로 둔다. 화면이 스키마 값을 고치지 않는다.
 */
import {createContext, useContext, useEffect, useRef, useState, type ReactNode} from 'react';
import {getAgentResponse, getMe, getPresentationData, getReplaySnapshot, getUsage, isLive, sendChatStream, type UsageInfo} from '@/lib/api';
import type {ProgressStage} from '@/lib/progress';
import {authEnabled, currentUser, onAuthChange, type AuthUser} from '@/lib/auth';
import type {AgentRequest, AgentResponse, ChatResponse} from '@/lib/types';

/** 입력창 대화 한 줄. 화면에만 두고 저장하지 않는다 (docs/specs/chat-search.md Out of Scope: 대화 기억) */
export interface ChatTurn { role: 'user' | 'assistant'; text: string; kind?: ChatResponse['kind'] }
const presentation = getPresentationData();
// 실제 모드는 빈 폼으로 시작한다. 세션 ID는 lib/api.ts가 요청 때 브라우저 값으로 채운다
const emptyRequest: AgentRequest = {bl_no: '', bl_type: 'HOUSE', sale_due_date: null, session_id: ''};

/** 서류 사진에서 사용자가 확인한 항차·입항 예정일. 되묻기 화면에 미리 채우는 데만 쓴다 (DocumentPanel). */
export interface DocHints { voyage_no: string | null; forwarder_eta: string | null }

interface AppState {
  data: typeof presentation; request: AgentRequest; result: AgentResponse | null;
  loading: boolean; error: string; replaying: boolean;
  /** 서버가 실제로 알린 처리 단계 (POST /api/chat/stream, docs/specs/chat-progress.md). 타이머로 만들지 않는다.
   * 마지막 칸이 지금 단계다. 데모 모드·/api/agent 조회·옛 서버는 소식이 없어 빈 배열이다 */
  stages: ProgressStage[];
  /** 지금 요청을 보낸 시각(Date.now()). 화면이 실제 경과 시간을 센다. 기다리지 않으면 null */
  pendingSince: number | null;
  lookup: (req: AgentRequest) => Promise<boolean>; replay: (id: string) => boolean;
  /** 문장 하나 보내기 (POST /api/chat). 화물 답이면 result를, 선박 검색이면 vessels를 바꾼다 */
  ask: (message: string) => Promise<boolean>;
  thread: ChatTurn[]; vessels: ChatResponse | null;
  /** 아래 결과 칸에 무엇을 보여 줄지. none이면 안내 문장이라 지난 결과를 숨긴다 (지난 화물은 기억만, 다시 보기 버튼으로 돌아온다) */
  view: 'cargo' | 'vessels' | 'none';
  /** 숨겨 둔 화물 결과를 다시 보인다 (선박 검색 뒤 "내 화물 결과로 돌아가기", 10-02 UI 점검 F4) */
  showCargo: () => void;
  /** 결과 칸의 React key. 새 화물 조회일 때만 바뀌고 후속 질문에는 그대로라 지도·펼친 근거가 다시 그려지지 않는다 (F10) */
  cargoKey: string;
  /** 로그인 기능이 켜졌는지, 세션 확인이 끝났는지, 누가 로그인했는지 */
  authEnabled: boolean; authReady: boolean; user: AuthUser | null;
  /** 운영자면 관리 탭을 보여 준다. 서버(GET /api/me)가 정한 값이고, 관리 API는 서버가 다시 확인한다 */
  isOperator: boolean;
  /** 회원 정보 입력을 마쳤나(GET /api/me). meReady 전에는 판단하지 않는다 (docs/specs/user-profile.md) */
  profileComplete: boolean; meReady: boolean; setProfileComplete: (v: boolean) => void;
  /** 운영자가 일시 정지한 계정 (GET /api/me 403 account_suspended) */
  suspended: boolean;
  docHints: DocHints | null; setDocHints: (h: DocHints | null) => void;
  /** 탈퇴·로그아웃 뒤 이전 사용자의 결과가 화면에 남지 않게 비운다 */
  reset: () => void;
  /** 오늘 LLM 토큰 사용량 (GET /api/usage). exhausted면 입력을 막는다 (docs/specs/token-quota.md) */
  usage: UsageInfo | null; refreshUsage: () => void;
}
const Context = createContext<AppState | null>(null);

export function AppProvider({children}:{children:ReactNode}) {
  const [request,setRequest] = useState<AgentRequest>(isLive ? emptyRequest : presentation.demo.choices[0].request as AgentRequest);
  const [result,setResult] = useState<AgentResponse|null>(null);
  const [loading,setLoading] = useState(false);
  const [stages,setStages] = useState<ProgressStage[]>([]); const [pendingSince,setPendingSince] = useState<number|null>(null);
  const [error,setError] = useState(''); const [replaying,setReplaying] = useState(false);
  const [user,setUser] = useState<AuthUser|null>(null);
  const [authReady,setAuthReady] = useState(!authEnabled);
  const [docHints,setDocHints] = useState<DocHints|null>(null);
  const [isOperator,setIsOperator] = useState(false);
  const [thread,setThread] = useState<ChatTurn[]>([]);
  const [vessels,setVessels] = useState<ChatResponse|null>(null);
  const [view,setView] = useState<'cargo'|'vessels'|'none'>('cargo');
  const [profileComplete,setProfileComplete] = useState(true);
  const [suspended,setSuspended] = useState(false);
  const [meReady,setMeReady] = useState(!authEnabled);
  const [usage,setUsage] = useState<UsageInfo|null>(null);
  const [cargoKey,setCargoKey] = useState('');
  // 요청을 마칠 때마다 다시 읽는다. 한도를 넘긴 요청은 끝까지 답하고, 그 뒤에 안내와 입력 막기가 걸린다
  function refreshUsage() { void getUsage().then(setUsage); }
  const inflight = useRef(false);

  // 로그인 상태는 브라우저에서만 안다. 첫 확인이 끝나기 전에는 로그인 화면을 깜빡 보여 주지 않도록 authReady로 막는다
  useEffect(() => {
    if (!authEnabled) return;
    let alive = true;
    void currentUser().then(u => { if (alive) { setUser(u); setAuthReady(true); } });
    const off = onAuthChange(u => setUser(u));
    return () => { alive = false; off(); };
  }, []);

  // 로그인한 사람이 바뀔 때마다 운영자인지 다시 묻는다. 로그인 전이면 묻지 않는다(어차피 401)
  useEffect(() => {
    if (!authReady || (authEnabled && !user)) { setIsOperator(false); setMeReady(!authEnabled); return; }
    let alive = true;
    setMeReady(false);
    void getMe().then(me => { if (alive) { setIsOperator(me.is_operator); setProfileComplete(me.profile_complete); setSuspended(!!me.suspended); setMeReady(true); } });
    refreshUsage();
    return () => { alive = false; };
  }, [authReady, user?.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  // 한도는 한국 시간 자정에 풀린다(docs/specs/token-quota.md). 탭을 켜 둔 채 자정을 넘기면 입력이 계속 막혀 있으므로
  // 창으로 돌아올 때와 10분마다 다시 읽는다 (10-02 UI 점검 F7). 데모 모드는 getUsage가 서버를 부르지 않는다
  useEffect(() => {
    if (!isLive) return;
    const onFocus = () => refreshUsage();
    window.addEventListener('focus', onFocus);
    const id = window.setInterval(refreshUsage, 10 * 60 * 1000);
    return () => { window.removeEventListener('focus', onFocus); window.clearInterval(id); };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  async function lookup(req: AgentRequest) {
    if (inflight.current) return false;
    inflight.current = true; setLoading(true); setError(''); setReplaying(false); setStages([]); setPendingSince(Date.now());
    // 정해진 칸 조회(POST /api/agent: 되묻기 답·다시 조회)는 단계 소식이 없다. 화면은 기다림과 경과 시간만 보인다
    try { const response = await getAgentResponse(req); setResult(response); setRequest(req); setView('cargo'); setCargoKey(response.trace_id); return true; }
    catch (e) { setError(e instanceof Error ? e.message : '조회하지 못했습니다. 다시 시도해 주세요.'); return false; }
    finally {setLoading(false);setPendingSince(null);inflight.current=false;refreshUsage();}
  }
  async function ask(message: string) {
    if (inflight.current) return false;
    inflight.current = true; setLoading(true); setError(''); setReplaying(false); setStages([]); setPendingSince(Date.now());
    // 화면에만 두는 대화. 최근 50줄까지 남기고 대화창은 스크롤로 본다 (ChatBar)
    setThread(t => [...t.slice(-49), {role: 'user', text: message}]);
    try {
      // 화면에 화물 카드가 실제로 보일 때만 그 화물을 함께 보낸다(후속 질문, "마스터로 다시"). B/L은 서버 안에서만 쓰인다.
      // 카드를 숨긴 상태(선박 표·안내 문장)에서 보낸 문장이 보이지 않는 화물의 후속 질문이 되지 않게 한다 (10-02 UI 점검 F5)
      const context = view === 'cargo' && result && request.bl_no ? request : null;
      const seen: ProgressStage[] = [];
      // 서버가 단계에 들어갈 때마다 목록에 더한다. 같은 단계가 두 번 오면(후속 질문이 재조회할 때 등) 한 번만 둔다
      const res = await sendChatStream(message, context,
        s => { seen.push(s); setStages(list => list.includes(s) ? list : [...list, s]); });
      setThread(t => [...t, {role: 'assistant', text: res.reply, kind: res.kind}]);
      if (res.kind === 'cargo' && res.agent && res.request) {
        if (context && result && isFollowUp(res.agent, res.request, context, result, seen)) {
          // 후속 질문의 답은 대화 칸에만 둔다. 서버는 지난 결과의 answer만 바꿔 돌려주므로(routers/agent.py _follow_up)
          // 판정 카드에는 원래 판정 설명을 남긴다 (F1). 관세청 처리 내역은 DB에 저장하지 않아 후속 응답에 빠져 오므로
          // 지난 값을 이어 쓴다 (F2, docs/specs/customs-detail.md). 판정·근거는 서버 응답 그대로다
          setResult({...res.agent, answer: result.answer,
            customs_detail: res.agent.customs_detail?.length ? res.agent.customs_detail : result.customs_detail});
        } else { setResult(res.agent); setRequest(res.request); setCargoKey(res.agent.trace_id); }
        setView('cargo');
      }
      if (res.kind === 'vessels') { setVessels(res); setView('vessels'); }
      // 안내 문장(B/L 없음 등)이면 아래의 지난 결과를 숨긴다. 새 답과 지난 카드가 섞여 보이지 않게
      if (res.kind === 'message') setView('none');
      return true;
    } catch (e) {
      // 실패는 대화 칸에만 알린다. 보고 있던 화물 결과는 그대로 둔다 (F3, 다시 조회 실패와 같은 방식)
      const msg = e instanceof Error ? e.message : '답하지 못했습니다. 다시 시도해 주세요.';
      setThread(t => [...t, {role: 'assistant', text: msg, kind: 'message'}]); return false;
    } finally { setLoading(false); setPendingSince(null); inflight.current = false; refreshUsage(); }
  }
  function replay(id: string) {
    if (inflight.current) return false;
    const snapshot = getReplaySnapshot(id); if (!snapshot) return false;
    // 선박 표를 보던 중이어도 재생한 화물이 보이게 화물 보기로 바꾼다 (10-02 발견: 표가 남아 재생 결과가 가려졌다)
    setResult(snapshot.response);setRequest(snapshot.request);setReplaying(true);setError('');setView('cargo');setCargoKey(snapshot.response.trace_id);return true;
  }
  function showCargo() { if (result) setView('cargo'); }
  function reset() { setThread([]); setVessels(null); setView('cargo'); setResult(null); setRequest(isLive ? emptyRequest : presentation.demo.choices[0].request as AgentRequest); setDocHints(null); setError(''); }

  return <Context.Provider value={{data:presentation,request,result,loading,stages,pendingSince,error,replaying,lookup,replay,ask,thread,vessels,view,showCargo,cargoKey,authEnabled,authReady,user,isOperator,profileComplete,meReady,setProfileComplete,suspended,docHints,setDocHints,reset,usage,refreshUsage}}>{children}</Context.Provider>;
}
/** 화물 답이 후속 질문의 답인지 고른다. 응답 계약(C1, ChatResponse)에 표시 칸이 없어 화면이 확인할 수 있는 사실로만 본다.
 * - 같은 B/L이 아니면 새 조회다
 * - 서버가 "답 작성(answer)" 단계를 알렸으면 후속 질문이다. 이 단계는 후속 질문만 보낸다 (routers/agent.py _follow_up)
 * - "통관 정보 조회(customs)"를 알렸고 answer가 없으면 새 판정이다
 * - 단계 소식이 없으면(데모, /api/chat 대신 보내기) 지난 근거가 같은 조회 시각 그대로 앞에 남아 있는지 본다.
 *   후속 답은 지난 결과에 도구 근거만 덧붙인다. 새 조회는 근거를 새로 받아 조회 시각이 바뀐다 */
function isFollowUp(next: AgentResponse, nextReq: AgentRequest, context: AgentRequest, prev: AgentResponse, stages: ProgressStage[]) {
  if (nextReq.bl_no !== context.bl_no) return false;
  if (stages.includes('answer')) return true;
  if (stages.includes('customs')) return false;
  if (next.status !== prev.status || next.verdict !== prev.verdict || next.evidence.length < prev.evidence.length) return false;
  return prev.evidence.every((e, i) => next.evidence[i].source === e.source && next.evidence[i].field === e.field && next.evidence[i].fetched_at === e.fetched_at);
}
export function useApp() { const ctx=useContext(Context);if(!ctx)throw new Error('AppProvider is required');return ctx; }
