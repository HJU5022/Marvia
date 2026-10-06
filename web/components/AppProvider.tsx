'use client';
/** 화면 전체가 같이 쓰는 상태: 마지막 요청·응답, 로그인 사용자, 서류 사진에서 확인한 값 (SDD 4.3, E3, E9, G3).
 * 응답은 받은 그대로 둔다. 화면이 스키마 값을 고치지 않는다.
 */
import {createContext, useContext, useEffect, useRef, useState, type ReactNode} from 'react';
import {usePathname, useRouter} from 'next/navigation';
import {deleteConversation, errorStatus, getAgentResponse, getConversation, getMe, getPresentationData, getReplaySnapshot, getUsage, getWatchChanges, isLive, listConversations, markWatchChangesSeen, newSessionId, sendChatStream, setActiveSession, currentSessionId, watchKey, type UsageInfo} from '@/lib/api';
import {verdictLabels} from '@/lib/format';
import type {ProgressStage} from '@/lib/progress';
import {authEnabled, currentUser, onAuthChange, type AuthUser} from '@/lib/auth';
import type {AgentRequest, AgentResponse, ChatCargo, ChatMap, ChatResponse, ConversationMessage, ConversationSummary, WatchChange, WatchOffer} from '@/lib/types';

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
    const base = `지켜보던 화물 ${c.label ?? c.bl_masked}의 판정이 ${verdictLabels[c.from_verdict]}에서 ${verdictLabels[c.to_verdict]} 등급으로 바뀌었어요.`;
    return c.reason ? `${base} ${c.reason}` : base;
  });
  return `${lines.join('\n')}\nB/L로 다시 조회하면 이유를 자세히 볼 수 있어요.`;
}
const presentation = getPresentationData();
// 실제 모드는 빈 폼으로 시작한다. 세션 ID는 lib/api.ts가 요청 때 브라우저 값으로 채운다
const emptyRequest: AgentRequest = {bl_no: '', bl_type: 'HOUSE', sale_due_date: null, session_id: ''};

/** 서버에 저장된 대화 한 줄을 말풍선으로. extra에는 그 턴이 처음 왔을 때의 화면용 값이 있어 지도·표·지켜보기 버튼이 같게 다시 그려진다 (10-06 결정) */
function toTurn(m: ConversationMessage): ChatTurn {
  const x = m.extra;
  return {role: m.role, text: m.text, kind: x?.kind, map: x?.map ?? null, cargos: x?.cargos ?? [], watchOffer: x?.watch_offer ?? null};
}

/** 로그인하지 않은(또는 대화 목록을 못 쓰는) 탭이 새로고침해도 대화를 이어 가려고 sessionStorage에 두는 값.
 * 탭을 닫으면 사라지고, 주소(URL)에는 대화 글을 넣지 않는다. 저장이 막힌 브라우저에서는 조용히 건너뛴다 (10-06 결정) */
const CHAT_STATE_KEY = 'marvia-chat-state';
interface SavedChat { session: string; thread: ChatTurn[]; request: AgentRequest; result: AgentResponse | null; view: 'cargo' | 'vessels' | 'none'; vessels: ChatResponse | null }

/** 서류 사진에서 사용자가 확인한 항차·입항 예정일·출항일. 항차·입항일은 되묻기 화면에 미리 채우는 데만 쓴다 (DocumentPanel).
 * departed_on(10-06)은 그 서류의 B/L(bl_no) 조회 때 서버로 보내 내 화물 현황 표 출항 칸에 적게 한다. 판정에는 안 쓰인다 */
export interface DocHints { voyage_no: string | null; forwarder_eta: string | null; bl_no: string; departed_on: string | null }

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
  /** 아래 결과 칸에 무엇을 보여 줄지. none이면 안내 문장이라 지난 결과를 숨긴다 (지난 화물은 기억만, 다시 보기 버튼으로 돌아온다) */
  view: 'cargo' | 'vessels' | 'none';
  /** 숨겨 둔 화물 결과를 다시 보인다 (선박 검색 뒤 "내 화물 결과로 돌아가기", 10-02 UI 점검 F4) */
  backToCargo: () => void;
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
  /** 지켜보는 중인 화물(정규화한 B/L → 켜짐/꺼짐). WatchToggle과 말풍선 버튼이 같이 쓴다. 값이 없으면 아직 모른다 (10-06 결정) */
  watching: Record<string, boolean>; setWatching: (blNo: string, on: boolean) => void;
  /** 대화 목록 (10-06 결정). conversationsOn이 false(로그아웃·로그인 기능 꺼짐·서버가 401/503)면 목록을 그리지 않고 탭 sessionStorage로 대화를 이어 간다 */
  conversationsOn: boolean; conversations: ConversationSummary[]; refreshConversations: () => Promise<void>;
  /** 지금 대화의 chat session_id. 열린 대화는 이 값이 목록의 id와 같다 */
  activeId: string;
  /** 서버에 저장된 것을 확인한(첫 답을 받았거나 열어 본) 대화 id. 이 값이 있을 때만 주소에 ?c=가 붙는다. 없으면 null */
  savedId: string | null;
  /** 대화를 불러오는 중 (메시지 보내기·다른 대화 열기를 잠시 막는다) */
  opening: boolean;
  newConversation: () => void; openConversation: (id: string) => Promise<boolean>; removeConversation: (id: string) => Promise<void>;
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
  const [watching,setWatchingMap] = useState<Record<string,boolean>>({});
  const [usage,setUsage] = useState<UsageInfo|null>(null);
  const [cargoKey,setCargoKey] = useState('');
  // 요청을 마칠 때마다 다시 읽는다. 한도를 넘긴 요청은 끝까지 답하고, 그 뒤에 안내와 입력 막기가 걸린다
  function refreshUsage() { void getUsage().then(setUsage); }
  const inflight = useRef(false);
  const router = useRouter(); const pathname = usePathname();
  const [conversations,setConversations] = useState<ConversationSummary[]>([]);
  // null = 목록을 아직 불러 보지 않았다. false = 서버가 401/503이라 쓸 수 없다 (그때는 sessionStorage로 이어 간다)
  const [convAvail,setConvAvail] = useState<boolean|null>(null);
  const [activeId,setActiveId] = useState('');
  const [savedId,setSavedId] = useState<string|null>(null);
  const [opening,setOpening] = useState(false);
  // 대화를 열거나 새로 시작할 때마다 올린다. 느리게 도착한 옛 응답(대화 내용, 먼저 말 걸기)이 새 화면을 덮지 않게 비교한다
  const epoch = useRef(0);
  const restored = useRef(false);
  const conversationsOn = isLive && authEnabled && !!user && convAvail !== false;
  // 목록을 못 쓰는 실제 모드 탭은 sessionStorage에 대화를 둔다
  const persistLocal = isLive && authReady && !conversationsOn;
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
    refreshUsage();
    return () => { alive = false; };
  }, [authReady, user?.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  // 다음 접속 때 먼저 말 걸기 (10-06 결정): 지난 접속 뒤 판정이 바뀐 지켜보는 화물이 있으면 대화의 첫 말풍선으로 알린다.
  // 말풍선을 thread에 넣은 뒤에 확인 처리한다(안 보여 준 알림을 지우지 않으려고). 알림은 덤이라 실패하면 조용히 넘어간다 (예전 배너와 같다)
  useEffect(() => {
    if (!isLive || !authEnabled || !authReady || !user) return;
    // 저장된 대화를 다시 연 주소(?c=)에는 말 걸지 않는다. 새 대화로 들어왔을 때만 보여 주고, 확인 처리도 그때 한다 (10-06 결정)
    if (new URLSearchParams(window.location.search).get('c')) return;
    let alive = true; const mine = epoch.current;
    void getWatchChanges().then(changes => {
      if (!alive || mine !== epoch.current || changes.length === 0) return;
      setThread(t => [{role: 'assistant', text: changesText(changes), kind: 'message'}, ...t]);
      void markWatchChangesSeen().catch(() => { /* 실패하면 다음 접속에 한 번 더 보인다 */ });
    }).catch(() => { /* 조용히 실패 */ });
    return () => { alive = false; };
  }, [authReady, user?.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  // 로그인하면 주소를 본다. ?c=<id>가 있으면 그 대화를 열고(새로고침·다른 기기·링크), 없으면 새 대화다 (새 session_id).
  // 새 대화의 주소는 첫 답을 받은 뒤에 붙인다. 서버가 그때 대화를 저장하므로, 그 전에 붙이면 새로고침이 404를 만난다
  useEffect(() => {
    if (!isLive || !authEnabled || !authReady || !user) { setConversations([]); setConvAvail(null); return; }
    try { window.sessionStorage.removeItem(CHAT_STATE_KEY); } catch { /* 저장소가 막혀 있어도 괜찮다 */ }
    const id = new URLSearchParams(window.location.search).get('c');
    if (id) void openConversation(id); else startSession(newSessionId());
    void refreshConversations();
  }, [authReady, user?.id]);  // eslint-disable-line react-hooks/exhaustive-deps

  // 목록을 못 쓰는 탭: 첫 화면에서 지난 대화를 되살린다 (이미 입력한 게 있으면 덮지 않는다)
  useEffect(() => {
    if (!persistLocal || restored.current) return;
    restored.current = true;
    if (thread.length > 0 || result) return;
    try {
      const raw = window.sessionStorage.getItem(CHAT_STATE_KEY); if (!raw) return;
      const saved = JSON.parse(raw) as SavedChat;
      if (!Array.isArray(saved.thread) || !saved.session) return;
      setActiveSession(saved.session); setActiveId(saved.session);
      setThread(saved.thread); setRequest(saved.request ?? emptyRequest); setResult(saved.result ?? null); setCargoKey(saved.result?.trace_id ?? ''); setVessels(saved.vessels ?? null); setView(saved.view ?? 'cargo');
    } catch { /* 깨진 값은 무시하고 빈 대화로 시작한다 */ }
  }, [persistLocal]);  // eslint-disable-line react-hooks/exhaustive-deps

  // 목록을 못 쓰는 탭: 대화가 바뀔 때마다 저장한다. 비어 있으면 저장하지 않는다(되살리기 전의 빈 값이 지난 대화를 지우지 않게)
  useEffect(() => {
    if (!persistLocal || (!thread.length && !result)) return;
    try {
      const saved: SavedChat = {session: currentSessionId(), thread, request, result, view, vessels};
      window.sessionStorage.setItem(CHAT_STATE_KEY, JSON.stringify(saved));
    } catch { /* 용량 초과·저장 금지는 건너뛴다. 새로고침하면 빈 대화로 시작할 뿐이다 */ }
  }, [persistLocal, thread, request, result, view, vessels]);

  /** 지금 대화의 session_id를 바꾼다. api.ts의 값이 다음 요청의 session_id가 되고, 화면의 activeId가 같이 바뀐다 */
  function startSession(id: string) { setActiveSession(id); setActiveId(id); }
  /** 주소만 바꾼다. 대화 글은 주소에 넣지 않고 id만 넣는다. 다른 화면(이력 등)에 있으면 내 화물로 옮겨 간다 */
  function syncUrl(id: string | null) {
    setSavedId(id);
    const url = id ? `/?c=${encodeURIComponent(id)}` : '/';
    if (pathname === '/') window.history.replaceState(null, '', url); else router.push(url);
  }
  async function refreshConversations() {
    try { setConversations(await listConversations()); setConvAvail(true); }
    catch (e) {
      // 로그인이 풀렸거나(401) DB가 없으면(503) 목록을 접고 탭 저장으로 간다. 그 밖의 일시 오류는 있던 목록을 그대로 둔다
      const status = errorStatus(e); if (status === 401 || status === 503) setConvAvail(false);
    }
  }
  /** 빈 새 대화. 지금 화면과 결과 칸을 비우고 새 session_id를 쓴다 (Langfuse 세션도 새로) */
  function newConversation() {
    if (inflight.current) return;  // 답을 기다리는 중에 바꾸면 곧 올 답이 새 화면에 섞인다
    epoch.current++; startSession(newSessionId()); clearScreen(); syncUrl(null);
  }
  function clearScreen() { setCargoKey(''); setThread([]); setVessels(null); setView('cargo'); setResult(null); setRequest(isLive ? emptyRequest : presentation.demo.choices[0].request as AgentRequest); setDocHints(null); setError(''); setWatchingMap({}); setReplaying(false); }
  /** 저장된 대화를 열어 화면을 되살린다. 말풍선은 messages(+extra)로, 아래 결과 칸은 context·result로 (단일 화물 답을 받았을 때와 같은 상태) */
  async function openConversation(id: string) {
    if (inflight.current) return false;
    const mine = ++epoch.current;
    setOpening(true); setError('');
    try {
      const c = await getConversation(id);
      if (mine !== epoch.current) return false;
      startSession(id);
      clearScreen();
      setThread(c.messages.slice(-50).map(toTurn));  // 화면에는 최근 50줄만 (ask와 같다)
      if (c.context && c.result) { setRequest({...c.context, session_id: id}); setResult(c.result); setCargoKey(c.result.trace_id); }
      // 마지막 답의 종류가 결과 칸을 정한다. ask()가 답마다 하는 것과 같다
      const last = [...c.messages].reverse().find(m => m.role === 'assistant');
      const kind = last?.extra?.kind;
      if (kind === 'vessels' && last?.extra) {
        setVessels({kind: 'vessels', reply: last.text, agent: null, request: null, vessels: [], place: null, ports: [], days: null, ...last.extra} as ChatResponse); setView('vessels');
      } else setView(kind === 'message' || !(c.context && c.result) ? 'none' : 'cargo');
      syncUrl(id);
      return true;
    } catch (e) {
      if (mine !== epoch.current) return false;
      const status = errorStatus(e);
      if (status === 401 || status === 503) setConvAvail(false);
      // 못 찾거나 못 읽으면 빈 새 대화로 시작하고 이유를 알린다. 주소의 ?c=도 지운다
      startSession(newSessionId()); clearScreen(); syncUrl(null);
      setError(status === 404 ? '찾는 대화가 없어요. 새 대화로 시작할게요.' : e instanceof Error ? e.message : '대화를 불러오지 못했어요.');
      return false;
    } finally { if (mine === epoch.current) setOpening(false); }
  }
  /** 대화 하나 삭제(DELETE /api/conversations/{id}). 지금 보던 대화면 새 대화로 간다. 실패하면 호출한 쪽(목록)이 이유를 보인다 */
  async function removeConversation(id: string) {
    await deleteConversation(id);
    if (id === activeId) { epoch.current++; startSession(newSessionId()); clearScreen(); syncUrl(null); }
    await refreshConversations();
  }

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
    catch (e) { setError(e instanceof Error ? e.message : '조회하지 못했어요. 다시 시도해 주세요.'); return false; }
    finally {setLoading(false);setPendingSince(null);inflight.current=false;refreshUsage();}
  }
  async function ask(message: string) {
    if (inflight.current || opening) return false;
    inflight.current = true; setLoading(true); setError(''); setReplaying(false); setStages([]); setPendingSince(Date.now());
    // 서버에 보낼 앞선 대화. 지금 질문을 더하기 전의 thread(이번 렌더의 값)를 잡아 둔다. 자르기는 chatBody가 한다 (최근 6줄, 500자)
    const history = thread;
    // 화면에만 두는 대화. 최근 50줄까지 남기고 대화창은 스크롤로 본다 (ChatBar)
    setThread(t => [...t.slice(-49), {role: 'user', text: message}]);
    try {
      // 화면에 화물 카드가 실제로 보일 때만 그 화물을 함께 보낸다(후속 질문, "마스터로 다시"). B/L은 서버 안에서만 쓰인다.
      // 카드를 숨긴 상태(선박 표·안내 문장)에서 보낸 문장이 보이지 않는 화물의 후속 질문이 되지 않게 한다 (10-02 UI 점검 F5)
      const context = view === 'cargo' && result && request.bl_no ? request : null;
      const seen: ProgressStage[] = [];
      // 서버가 단계에 들어갈 때마다 목록에 더한다. 같은 단계가 두 번 오면(후속 질문이 재조회할 때 등) 한 번만 둔다
      // 서류에서 확인한 출항일이 있으면 그 B/L과 함께 보낸다. 서버가 그 B/L 조회에만 실어 화물 표에 적는다 (10-06)
      const document = docHints?.departed_on ? {bl_no: docHints.bl_no, departed_on: docHints.departed_on} : null;
      const res = await sendChatStream(message, context,
        s => { seen.push(s); setStages(list => list.includes(s) ? list : [...list, s]); }, history, document);
      setThread(t => [...t, {role: 'assistant', text: res.reply, kind: res.kind, map: res.map ?? null, cargos: res.cargos ?? [], watchOffer: res.watch_offer ?? null}]);
      // 대화로 지켜보기를 켜고 껐으면 결과 칸의 버튼·말풍선 버튼이 같은 상태를 보게 한다
      if (res.watch_set) setWatching(res.watch_set.bl_no, res.watch_set.on);
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
      // 서버가 이 턴을 저장했다. 주소에 대화 id를 붙이고 목록을 새로 읽는다. 제목은 조금 늦게 생길 수 있어 한 번 더 읽는다 (10-06 결정)
      if (conversationsOn) { syncUrl(currentSessionId()); void refreshConversations(); setTimeout(() => void refreshConversations(), 3000); }
      return true;
    } catch (e) {
      // 실패는 대화 칸에만 알린다. 보고 있던 화물 결과는 그대로 둔다 (F3, 다시 조회 실패와 같은 방식)
      const msg = e instanceof Error ? e.message : '답을 만들지 못했어요. 다시 시도해 주세요.';
      setThread(t => [...t, {role: 'assistant', text: msg, kind: 'message'}]); return false;
    } finally { setLoading(false); setPendingSince(null); inflight.current = false; refreshUsage(); }
  }
  function showCargo(agent: AgentResponse, req: AgentRequest) {
    if (inflight.current) return;  // 조회 중에 바꾸면 곧 도착할 새 결과와 섞인다
    setResult(agent); setRequest(req); setCargoKey(agent.trace_id); setReplaying(false); setError(''); setView('cargo');
  }
  function replay(id: string) {
    if (inflight.current) return false;
    const snapshot = getReplaySnapshot(id); if (!snapshot) return false;
    // 선박 표를 보던 중이어도 재생한 화물이 보이게 화물 보기로 바꾼다 (10-02 발견: 표가 남아 재생 결과가 가려졌다)
    setResult(snapshot.response);setRequest(snapshot.request);setReplaying(true);setError('');setView('cargo');setCargoKey(snapshot.response.trace_id);return true;
  }
  /** 숨겨 둔 화물 결과를 다시 보인다 (선박 검색 뒤 "내 화물 결과로 돌아가기"). 채팅 표 행을 여는 showCargo(agent, request)와 이름이 겹쳐 따로 부른다 */
  function backToCargo() { if (result) setView('cargo'); }
  // 탈퇴·로그아웃·기록 삭제 뒤: 화면을 비우고 탭에 저장해 둔 대화도 지운다. 주소의 ?c=도 지워 다음 사용자가 이전 대화를 열려 하지 않게 한다
  function reset() {
    epoch.current++; clearScreen(); startSession(isLive ? newSessionId() : ''); if (isLive) syncUrl(null);
    try { window.sessionStorage.removeItem(CHAT_STATE_KEY); } catch { /* 괜찮다 */ }
  }

  return <Context.Provider value={{data:presentation,request,result,loading,stages,pendingSince,error,replaying,lookup,replay,ask,showCargo,backToCargo,cargoKey,thread,vessels,view,authEnabled,authReady,user,isOperator,profileComplete,meReady,setProfileComplete,suspended,docHints,setDocHints,reset,usage,refreshUsage,watching,setWatching,conversationsOn,conversations,refreshConversations,activeId,savedId,opening,newConversation,openConversation,removeConversation}}>{children}</Context.Provider>;
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
