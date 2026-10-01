'use client';
/** 화면 전체가 같이 쓰는 상태: 마지막 요청·응답, 로그인 사용자, 서류 사진에서 확인한 값 (SDD 4.3, E3, E9, G3).
 * 응답은 받은 그대로 둔다. 화면이 스키마 값을 고치지 않는다.
 */
import {createContext, useContext, useEffect, useRef, useState, type ReactNode} from 'react';
import {getAgentResponse, getMe, getPresentationData, getReplaySnapshot, isLive, sendChat} from '@/lib/api';
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
  loading: boolean; stage: number; error: string; replaying: boolean;
  lookup: (req: AgentRequest) => Promise<boolean>; replay: (id: string) => boolean;
  /** 문장 하나 보내기 (POST /api/chat). 화물 답이면 result를, 선박 검색이면 vessels를 바꾼다 */
  ask: (message: string) => Promise<boolean>;
  thread: ChatTurn[]; vessels: ChatResponse | null; view: 'cargo' | 'vessels';
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
}
const Context = createContext<AppState | null>(null);

export function AppProvider({children}:{children:ReactNode}) {
  const [request,setRequest] = useState<AgentRequest>(isLive ? emptyRequest : presentation.demo.choices[0].request as AgentRequest);
  const [result,setResult] = useState<AgentResponse|null>(null);
  const [loading,setLoading] = useState(false); const [stage,setStage] = useState(0);
  const [error,setError] = useState(''); const [replaying,setReplaying] = useState(false);
  const [user,setUser] = useState<AuthUser|null>(null);
  const [authReady,setAuthReady] = useState(!authEnabled);
  const [docHints,setDocHints] = useState<DocHints|null>(null);
  const [isOperator,setIsOperator] = useState(false);
  const [thread,setThread] = useState<ChatTurn[]>([]);
  const [vessels,setVessels] = useState<ChatResponse|null>(null);
  const [view,setView] = useState<'cargo'|'vessels'>('cargo');
  const [profileComplete,setProfileComplete] = useState(true);
  const [suspended,setSuspended] = useState(false);
  const [meReady,setMeReady] = useState(!authEnabled);
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
    return () => { alive = false; };
  }, [authReady, user?.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function lookup(req: AgentRequest) {
    if (inflight.current) return false;
    inflight.current = true; setLoading(true); setError(''); setStage(0); setReplaying(false);
    // 화면 타이머다. 백엔드는 진행 이벤트를 보내지 않는다
    const a = setTimeout(()=>setStage(1),350); const b = setTimeout(()=>setStage(2),700);
    try { const response = await getAgentResponse(req); setResult(response); setRequest(req); return true; }
    catch (e) { setError(e instanceof Error ? e.message : '조회하지 못했습니다. 다시 시도해 주세요.'); return false; }
    finally {clearTimeout(a);clearTimeout(b);setLoading(false);inflight.current=false;}
  }
  async function ask(message: string) {
    if (inflight.current) return false;
    inflight.current = true; setLoading(true); setError(''); setStage(0); setReplaying(false);
    setThread(t => [...t.slice(-9), {role: 'user', text: message}]);
    const a = setTimeout(()=>setStage(1),350); const b = setTimeout(()=>setStage(2),700);
    try {
      // 지금 보고 있는 화물이 있으면 함께 보낸다(후속 질문, "마스터로 다시"). B/L은 서버 안에서만 쓰인다
      const res = await sendChat(message, result && request.bl_no ? request : null);
      setThread(t => [...t, {role: 'assistant', text: res.reply, kind: res.kind}]);
      if (res.kind === 'cargo' && res.agent && res.request) { setResult(res.agent); setRequest(res.request); setView('cargo'); }
      if (res.kind === 'vessels') { setVessels(res); setView('vessels'); }
      return true;
    } catch (e) {
      const msg = e instanceof Error ? e.message : '답하지 못했습니다. 다시 시도해 주세요.';
      setError(msg); setThread(t => [...t, {role: 'assistant', text: msg, kind: 'message'}]); return false;
    } finally { clearTimeout(a); clearTimeout(b); setLoading(false); inflight.current = false; }
  }
  function replay(id: string) {
    if (inflight.current) return false;
    const snapshot = getReplaySnapshot(id); if (!snapshot) return false;
    setResult(snapshot.response);setRequest(snapshot.request);setReplaying(true);setError('');return true;
  }
  function reset() { setThread([]); setVessels(null); setView('cargo'); setResult(null); setRequest(isLive ? emptyRequest : presentation.demo.choices[0].request as AgentRequest); setDocHints(null); setError(''); }

  return <Context.Provider value={{data:presentation,request,result,loading,stage,error,replaying,lookup,replay,ask,thread,vessels,view,authEnabled,authReady,user,isOperator,profileComplete,meReady,setProfileComplete,suspended,docHints,setDocHints,reset}}>{children}</Context.Provider>;
}
export function useApp() { const ctx=useContext(Context);if(!ctx)throw new Error('AppProvider is required');return ctx; }
