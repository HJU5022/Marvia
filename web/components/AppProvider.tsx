'use client';
/** 화면 전체가 같이 쓰는 상태: 마지막 요청·응답, 로그인 사용자, 서류 사진에서 확인한 값 (SDD 4.3, E3, E9, G3).
 * 응답은 받은 그대로 둔다. 화면이 스키마 값을 고치지 않는다.
 */
import {createContext, useContext, useEffect, useRef, useState, type ReactNode} from 'react';
import {getAgentResponse, getMe, getPresentationData, getReplaySnapshot, getWatchChanges, isLive, markWatchChangesSeen, sendChatStream, watchKey} from '@/lib/api';
import {verdictLabels} from '@/lib/format';
import type {ProgressStage} from '@/lib/progress';
import {authEnabled, currentUser, onAuthChange, type AuthUser} from '@/lib/auth';
import type {AgentRequest, AgentResponse, ChatCargo, ChatMap, ChatResponse, WatchChange, WatchOffer} from '@/lib/types';

/** 입력창 대화 한 줄. 화면에만 두고 저장하지 않는다 (docs/specs/chat-search.md Out of Scope: 대화 기억) */
export interface ChatTurn { role: 'user' | 'assistant'; text: string; kind?: ChatResponse['kind'];
  /** 위치를 조회한 답이면 말풍선 아래 작은 지도에 쓴다. 서버로 되돌려 보내지 않는다(lib/api.ts chatBody는 role, text만) */
  map?: ChatMap | null;
  /** B/L을 2~3개 물었을 때 조회한 화물 표 (ChatCargoTable). 서버로 되돌려 보내지 않는다 */
  cargos?: ChatCargo[];
  /** 에이전트가 이 화물을 지켜보자고 제안한 답이면 말풍선 아래에 버튼을 그린다 (WatchOfferAction, 10-06 결정). 서버로 되돌려 보내지 않는다 */
  watchOffer?: WatchOffer | null }

/** 접속하자마자 보이는 첫 말풍선 글. 코드가 쓴 문장이고 서버가 준 값만 쓴다. 서버가 reason을 주면 덧붙이고, 없으면 지어내지 않는다 (10-06 결정) */
function changesText(changes: WatchChange[]): string {
  const lines = changes.map(c => {
    const base = `지켜보던 화물 ${c.label ?? c.bl_masked}의 판정이 '${verdictLabels[c.from_verdict]}'에서 '${verdictLabels[c.to_verdict]}'(으)로 바뀌었어요.`;
    return c.reason ? `${base} ${c.reason}` : base;
  });
  return `${lines.join('\n')}\nB/L로 다시 조회하면 이유를 자세히 볼 수 있어요.`;
}
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
  /** 채팅 표에서 고른 화물로 아래 결과 칸을 바꾼다. 단일 화물 답을 받았을 때와 같은 상태 바꿈이다 (다음 질문의 문맥도 이 화물) */
  showCargo: (agent: AgentResponse, request: AgentRequest) => void;
  thread: ChatTurn[]; vessels: ChatResponse | null;
  /** 아래 결과 칸에 무엇을 보여 줄지. none이면 안내·실패라 지난 결과를 숨긴다 (지난 화물은 후속 질문용으로 기억만) */
  view: 'cargo' | 'vessels' | 'none';
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
  /** 지켜보는 중인 화물(정규화한 B/L → 켜짐/꺼짐). WatchToggle과 말풍선 버튼이 같이 쓴다. 값이 없으면 아직 모른다 (10-06 결정) */
  watching: Record<string, boolean>; setWatching: (blNo: string, on: boolean) => void;
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
  const [watching,setWatchingMap] = useState<Record<string,boolean>>({});
  const inflight = useRef(false);
  function setWatching(blNo: string, on: boolean) { setWatchingMap(m => m[watchKey(blNo)] === on ? m : {...m, [watchKey(blNo)]: on}); }

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

  // 다음 접속 때 먼저 말 걸기 (10-06 결정): 지난 접속 뒤 판정이 바뀐 지켜보는 화물이 있으면 대화의 첫 말풍선으로 알린다.
  // 말풍선을 thread에 넣은 뒤에 확인 처리한다(안 보여 준 알림을 지우지 않으려고). 알림은 덤이라 실패하면 조용히 넘어간다 (예전 배너와 같다)
  useEffect(() => {
    if (!isLive || !authEnabled || !authReady || !user) return;
    let alive = true;
    void getWatchChanges().then(changes => {
      if (!alive || changes.length === 0) return;
      setThread(t => [{role: 'assistant', text: changesText(changes), kind: 'message'}, ...t]);
      void markWatchChangesSeen().catch(() => { /* 실패하면 다음 접속에 한 번 더 보인다 */ });
    }).catch(() => { /* 조용히 실패 */ });
    return () => { alive = false; };
  }, [authReady, user?.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function lookup(req: AgentRequest) {
    if (inflight.current) return false;
    inflight.current = true; setLoading(true); setError(''); setReplaying(false); setStages([]); setPendingSince(Date.now());
    // 정해진 칸 조회(POST /api/agent: 되묻기 답·다시 조회)는 단계 소식이 없다. 화면은 기다림과 경과 시간만 보인다
    try { const response = await getAgentResponse(req); setResult(response); setRequest(req); setView('cargo'); return true; }
    catch (e) { setError(e instanceof Error ? e.message : '조회하지 못했습니다. 다시 시도해 주세요.'); return false; }
    finally {setLoading(false);setPendingSince(null);inflight.current=false;}
  }
  async function ask(message: string) {
    if (inflight.current) return false;
    inflight.current = true; setLoading(true); setError(''); setReplaying(false); setStages([]); setPendingSince(Date.now());
    // 서버에 보낼 앞선 대화. 지금 질문을 더하기 전의 thread(이번 렌더의 값)를 잡아 둔다. 자르기는 chatBody가 한다 (최근 6줄, 500자)
    const history = thread;
    // 화면에만 두는 대화. 최근 50줄까지 남기고 대화창은 스크롤로 본다 (ChatBar)
    setThread(t => [...t.slice(-49), {role: 'user', text: message}]);
    try {
      // 지금 보고 있는 화물이 있으면 함께 보낸다(후속 질문, "마스터로 다시"). B/L은 서버 안에서만 쓰인다
      // 서버가 단계에 들어갈 때마다 목록에 더한다. 같은 단계가 두 번 오면(후속 질문이 재조회할 때 등) 한 번만 둔다
      const res = await sendChatStream(message, result && request.bl_no ? request : null,
        s => setStages(list => list.includes(s) ? list : [...list, s]), history);
      setThread(t => [...t, {role: 'assistant', text: res.reply, kind: res.kind, map: res.map ?? null, cargos: res.cargos ?? [], watchOffer: res.watch_offer ?? null}]);
      // 대화로 지켜보기를 켜고 껐으면 결과 칸의 버튼·말풍선 버튼이 같은 상태를 보게 한다
      if (res.watch_set) setWatching(res.watch_set.bl_no, res.watch_set.on);
      if (res.kind === 'cargo' && res.agent && res.request) { setResult(res.agent); setRequest(res.request); setView('cargo'); }
      if (res.kind === 'vessels') { setVessels(res); setView('vessels'); }
      // 안내 문장(B/L 없음 등)이면 아래의 지난 결과를 숨긴다. 새 답과 지난 카드가 섞여 보이지 않게
      if (res.kind === 'message') setView('none');
      return true;
    } catch (e) {
      const msg = e instanceof Error ? e.message : '답하지 못했습니다. 다시 시도해 주세요.';
      setError(msg); setView('none'); setThread(t => [...t, {role: 'assistant', text: msg, kind: 'message'}]); return false;
    } finally { setLoading(false); setPendingSince(null); inflight.current = false; }
  }
  function showCargo(agent: AgentResponse, req: AgentRequest) {
    if (inflight.current) return;  // 조회 중에 바꾸면 곧 도착할 새 결과와 섞인다
    setResult(agent); setRequest(req); setReplaying(false); setError(''); setView('cargo');
  }
  function replay(id: string) {
    if (inflight.current) return false;
    const snapshot = getReplaySnapshot(id); if (!snapshot) return false;
    // 선박 표를 보던 중이어도 재생한 화물이 보이게 화물 보기로 바꾼다 (10-02 발견: 표가 남아 재생 결과가 가려졌다)
    setResult(snapshot.response);setRequest(snapshot.request);setReplaying(true);setError('');setView('cargo');return true;
  }
  function reset() { setThread([]); setVessels(null); setView('cargo'); setResult(null); setRequest(isLive ? emptyRequest : presentation.demo.choices[0].request as AgentRequest); setDocHints(null); setError(''); setWatchingMap({}); }

  return <Context.Provider value={{data:presentation,request,result,loading,stages,pendingSince,error,replaying,lookup,replay,ask,showCargo,thread,vessels,view,authEnabled,authReady,user,isOperator,profileComplete,meReady,setProfileComplete,suspended,docHints,setDocHints,reset,watching,setWatching}}>{children}</Context.Provider>;
}
export function useApp() { const ctx=useContext(Context);if(!ctx)throw new Error('AppProvider is required');return ctx; }
