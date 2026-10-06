'use client';
/** AI 입력창 (docs/specs/chat-search.md). 홈 화면의 주 기능이라 가운데 넓은 자리에 둔다 (강사 피드백 10-02, 구현작업서 4절).
 * 문장은 POST /api/chat/stream으로 가고, 서버가 B/L을 가린 뒤 LLM이 의도(화물 조회·후속 질문·입항 선박 검색)를 고른다.
 * 기다리는 동안은 서버가 알린 실제 처리 단계만 보인다 (docs/specs/chat-progress.md). 타이머로 단계를 만들지 않는다.
 * 서류 사진은 입력을 돕는 보조 동작이라 드로어에서 확인한 뒤 문장에 넣는다. 읽은 값으로 바로 조회하지 않는다.
 * 화면을 내려 입력창이 안 보이면 "AI에게 이어서 물어보기" 버튼이 나타나 입력창으로 돌려보낸다.
 */
import {useEffect, useRef, useState, type FormEvent, type KeyboardEvent} from 'react';
import {createPortal} from 'react-dom';
import {ArrowUp, Camera, Check, FileText, LoaderCircle, MessageCircle, PackageSearch, Ship, Sparkles} from 'lucide-react';
import {VerdictBadge} from './Shared';
import {useApp} from './AppProvider';
import {DocumentPanel, type DocumentValues} from './DocumentPanel';
import {Drawer} from './Drawer';
import {ChatMiniMap} from './ChatMiniMap';
import {ChatCargoTable} from './ChatCargoTable';
import {WatchOfferAction} from './WatchOfferAction';
import {isLive, QUOTA_MESSAGE} from '@/lib/api';
import {onComposerRequest} from '@/lib/composer';
import {stageLabels, type ProgressStage} from '@/lib/progress';

const MAX = 500;  // routers/chat.py ChatRequest.message max_length

/** 처음 보는 사람을 위한 예시 문장. 누르면 입력창에 채우기만 한다(보내기는 사용자가). 실제 모드는 누구나 바로 결과를 볼 수 있는
 * 입항 선박 검색만 둔다 (데모 B/L을 실제 사용자에게 보여 주지 않는다, 10-01). 데모 모드는 가공 B/L */
const EXAMPLES = isLive
  ? ['이번 주 일본에서 부산 들어오는 배 보여줘', '상하이에서 출발해서 부산 오는 배 있어?', '2주 안에 베트남에서 들어오는 배 알려줘', '3일 안에 부산 들어오는 배 전부']
  : ['MRVDEMO1101 화물 괜찮아?', 'MRVDEMO1107 지금 조치해야 해?', '중국에서 부산 들어오는 배 보여줘'];

/** 사용자가 움직임 줄이기를 켰으면 부드러운 스크롤을 쓰지 않는다 (MDN prefers-reduced-motion) */
function scrollBehavior(): ScrollBehavior {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
}

/** 답 글 속 http(s) 주소만 누를 수 있는 링크로 바꾼다. 서버는 "웹 참고: 제목 (주소)"를 평문으로 붙인다(services/chat.py WEB_NOTE).
 * 주소는 서버가 가져온 검색 결과에서만 오지만, 그래도 http·https만 링크로 만들고 새 탭으로 연다(noopener: 열린 쪽이 이 창을 못 건드리게).
 * 닫는 괄호는 주소에 넣지 않는다: "(https://...)"의 ")"가 주소 끝에 붙지 않게 (10-06 정운 지적: 웹 참고 링크가 안 눌림) */
const URL_PATTERN = /(https?:\/\/[^\s)]+)/g;
function linkify(text: string) {
  return text.split(URL_PATTERN).map((part, i) =>
    i % 2 === 1 ? <a key={i} href={part} target="_blank" rel="noopener noreferrer" className="chat-link">{part}</a> : part);
}

export function ChatBar({idle = false, onShowDetail}: {idle?: boolean; onShowDetail?: () => void}) {
  const {ask, loading, stages, pendingSince, thread, result, request, setDocHints, usage, view} = useApp();
  // 판정 배지·할 일 한 줄은 "가장 최근 화물 답" 말풍선에만 붙인다. ChatTurn에는 판정이 없어 지금 보는 result(가장 최근 화물 답)에서 읽는다. 지어내지 않는다.
  // B/L 여러 개를 비교한 답은 표가 줄마다 배지를 가지고 있어 붙이지 않는다
  const verdictTurn = view === 'cargo' && result?.verdict ? thread.map((t, i) => t.role === 'assistant' && t.kind === 'cargo' && !(t.cargos && t.cargos.length > 1) ? i : -1).reduce((a, b) => Math.max(a, b), -1) : -1;
  // 화물 카드가 실제로 보일 때만 "이 화물"로 안내한다. AppProvider.ask도 같은 조건으로 화물을 함께 보낸다 (10-02 UI 점검 F5)
  const cargoShown = view === 'cargo' && !!result && !!request.bl_no;
  // 하루 토큰 한도를 다 쓰면 입력·서류 사진을 막는다. 서버도 429로 막는다 (docs/specs/token-quota.md)
  const blocked = !!usage?.exhausted;
  const [text, setText] = useState('');
  const [docOpen, setDocOpen] = useState(false);
  const [away, setAway] = useState(false);  // 입력창이 화면 밖이면 true
  // 다른 입력칸에 글을 쓰는 중이면 true. 휴대폰에서 떠 있는 "이어서 물어보기" 버튼이 입력칸을 덮지 않게 그동안 숨긴다 (F18)
  const [typing, setTyping] = useState(false);
  // 입력창에 이미 글이 있을 때 예시·카드가 채우려던 문장. 덮어쓰지 않고 바꿀지 묻는다 (F11)
  const [offer, setOffer] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);  // 맨 아래를 보고 있으면 true. 위로 올려 읽는 중에는 새 메시지가 와도 끌어내리지 않는다

  // 새 메시지·답 대기 표시가 생기면 대화 칸만 맨 아래로 (위 대화를 읽는 중이면 그대로). 페이지 전체는 움직이지 않는다
  useEffect(() => {
    const el = threadRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [thread, loading, result]);
  function onScroll() {
    const el = threadRef.current;
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  // 입력창이 화면에서 벗어났는지 본다. 벗어나면 돌아가기 버튼을 띄운다
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(([entry]) => setAway(!entry.isIntersecting), {threshold: 0});
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // 다른 카드가 "AI에게 묻기"를 누르면 입력창으로 와서 글자를 채운다 (lib/composer.ts). 쓰던 글이 있으면 덮지 않고 묻는다 (F11)
  const textRef = useRef(text);
  textRef.current = text;
  useEffect(() => onComposerRequest(t => {
    if (t !== undefined) offerText(t);
    goToComposer();
  }), []);  // eslint-disable-line react-hooks/exhaustive-deps

  // 입력칸(input·textarea·select)에 포커스가 있는지 본다. 화면 키보드가 올라온 동안 떠 있는 버튼을 숨기는 데만 쓴다
  useEffect(() => {
    const isField = (el: EventTarget | null) => el instanceof HTMLElement && el.matches('input, textarea, select, [contenteditable="true"]');
    const onIn = (e: FocusEvent) => setTyping(isField(e.target));
    const onOut = () => setTyping(isField(document.activeElement) && document.activeElement !== document.body);
    document.addEventListener('focusin', onIn);
    document.addEventListener('focusout', onOut);
    return () => { document.removeEventListener('focusin', onIn); document.removeEventListener('focusout', onOut); };
  }, []);

  /** 입력창이 비어 있으면 바로 채우고, 쓰던 글이 있으면 바꿀지 묻는다 */
  function offerText(t: string) {
    const next = t.slice(0, MAX);
    const now = textRef.current.trim();
    if (!now || now === next.trim()) { setText(next); setOffer(null); }
    else setOffer(next);
  }

  function goToComposer() {
    wrapRef.current?.scrollIntoView({behavior: scrollBehavior(), block: 'center'});
    inputRef.current?.focus({preventScroll: true});
  }

  async function send(message: string) {
    const m = message.trim();
    if (!m || loading || blocked || m.length > MAX) return;  // 보내는 중이거나 한도를 다 썼으면 보내지 않는다
    setText('');
    stick.current = true;  // 내가 보낸 것은 항상 보이게
    const ok = await ask(m);
    // 실패하면 쓴 문장을 돌려준다. 그 사이 새로 쓴 글자가 있으면 덮지 않는다
    if (!ok) setText(t => t || m);
  }
  function submit(e: FormEvent) { e.preventDefault(); void send(text); }
  // Enter로 보내고, Shift+Enter는 줄바꿈 (한글 조합 중 Enter는 무시)
  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(text); }
  }
  function fill(example: string) { if (blocked) return; offerText(example); inputRef.current?.focus(); }
  function applyDocument(v: DocumentValues) {
    setDocOpen(false);
    // MRN이 있으면 문장에 같이 넣는다. 서버가 코드로 뽑아 세관 미등록 때 배를 찾는다 (LLM에는 안 감)
    setText(t => `${v.bl_no}${v.mrn ? ` MRN ${v.mrn}` : ''} ${t}`.trim());
    setDocHints(v.voyage_no || v.forwarder_eta || v.departed_on ? {voyage_no: v.voyage_no, forwarder_eta: v.forwarder_eta, bl_no: v.bl_no, departed_on: v.departed_on} : null);
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  // 판정 답 말풍선 안의 배지·할 일 한 줄. 대화가 비어 있는데 결과만 있는 경우(데모 첫 화면, 저장된 판정 열기)도 같은 모양으로 그린다 (시안 2-2)
  const verdictBlock = result?.verdict ? <div className="chat-verdict"><VerdictBadge verdict={result.verdict} size="lg"/>{result.actions[0] && <p className="chat-todo"><span>지금 할 일</span>{result.actions[0]}</p>}<button type="button" className="chat-show-detail" onClick={onShowDetail}>결과 보기</button></div> : null;
  // 대화가 없고 답할 글만 있는 첫 화면(.chat-seed는 .chat-turn이 아니다: 실제 주고받은 말만 .chat-turn으로 센다): 결과 칸의 answer를 그대로 답 말풍선으로 보인다 (지어내지 않는다, 서버 값)
  const seedAnswer = thread.length === 0 && view === 'cargo' && result && result.status !== 'insufficient' && result.answer ? result : null;
  const empty = idle && !loading && thread.length === 0;

  return <section className="ask" aria-label="AI에게 묻기">
    {/* 대화는 이 칸 안에서만 스크롤하고, 입력창은 아래에 고정한다 (시안 2-1·2-2). 페이지 전체는 움직이지 않는다 */}
    <div className="chat-scroll" ref={threadRef} onScroll={onScroll} role="log" aria-label="대화" tabIndex={0}>
      {empty ? <div className="chat-empty">
        <span className="chat-empty-icon" aria-hidden="true"><MessageCircle size={22}/></span>
        <h2>어떤 화물을 확인할까요?</h2>
        <p>B/L 번호를 조회하면 배 위치와 통관 단계를 함께 보여드려요.</p>
        <div className="feature-tiles">
          <button type="button" onClick={() => isLive ? goToComposer() : fill(EXAMPLES[0])} disabled={blocked}><PackageSearch size={20}/>B/L 번호로 조회하기</button>
          <button type="button" onClick={() => fill(isLive ? EXAMPLES[0] : EXAMPLES[2])} disabled={blocked}><Ship size={20}/>입항 예정 선박 찾기</button>
          <button type="button" onClick={() => setDocOpen(true)} disabled={blocked}><FileText size={20}/>서류 사진 올리기</button>
        </div>
      </div> : <ol className="chat-thread" aria-live="polite">
        {thread.map((t, i) => <li key={i} className={`chat-turn ${t.role}`}>
          <div className="chat-body"><div className="chat-bubble"><p>{t.role === 'assistant' ? linkify(t.text) : t.text}</p>{i === verdictTurn && verdictBlock}</div>{t.role === 'assistant' && t.cargos && t.cargos.length > 1 ? <ChatCargoTable cargos={t.cargos}/> : t.role === 'assistant' && t.map && <ChatMiniMap map={t.map}/>}{t.role === 'assistant' && t.watchOffer && <WatchOfferAction offer={t.watchOffer}/>}</div></li>)}
        {seedAnswer && <li className="chat-seed"><div className="chat-body"><div className="chat-bubble"><p>{seedAnswer.answer}</p>{verdictBlock}</div></div></li>}
      </ol>}
      {loading && pendingSince !== null && <Pending stages={stages} since={pendingSince}/>}
    </div>

    <div className="chat-dock">
      {blocked ? <p className="quota-note blocked" role="alert">{QUOTA_MESSAGE}</p>
        : usage?.near_limit && usage.remaining !== null ? <p className="quota-note" role="status">오늘 쓸 수 있는 AI 사용량이 얼마 남지 않았어요</p> : null}
      {offer !== null && <div className="fill-offer" role="status"><span>입력 중인 글이 있어요. 이 문장으로 바꿀까요? <strong>{offer}</strong></span>
        <button type="button" className="button secondary" onClick={() => { setText(offer); setOffer(null); inputRef.current?.focus(); }}>바꾸기</button>
        <button type="button" className="button text-button" onClick={() => { setOffer(null); inputRef.current?.focus(); }}>쓰던 글 유지하기</button></div>}
      <div className="composer-wrap" ref={wrapRef}>
        <form className="composer" onSubmit={submit}>
          <label htmlFor="chat-input" className="sr-only">Marvia에게 질문하기</label>
          <textarea id="chat-input" ref={inputRef} value={text} onChange={e => setText(e.target.value)} onKeyDown={onKey} rows={1} maxLength={MAX} disabled={blocked}
            placeholder={cargoShown ? '이 화물에 대해 더 물어보세요' : 'B/L 번호를 입력해 주세요'}
            aria-describedby="chat-help" autoComplete="off" spellCheck={false}/>
          <div className="composer-foot">
            <button type="button" className="doc-trigger" onClick={() => setDocOpen(true)} disabled={loading || blocked}><Camera size={16}/>서류 사진으로 채우기</button>
            <div className="composer-send">
              {/* 글자 수는 쓰기 시작한 뒤에만 보인다. 빈 입력창에 숫자를 늘 두면 어수선하다 */}
              {text.length > 0 && <span className="mono chat-count" aria-label={`${text.length}자 입력, 최대 ${MAX}자`}>{text.length} / {MAX}</span>}
              <button type="submit" className="send" disabled={loading || blocked || !text.trim()} aria-label="AI에게 질문 보내기">
                {loading ? <LoaderCircle size={20} className="spin"/> : <ArrowUp size={21}/>}</button>
            </div>
          </div>
        </form>
      </div>
      {/* 시작 문장: 대화가 비어 있을 때만. 누르면 입력창에 채우기만 한다 */}
      {empty && <div className="chat-examples" aria-label="질문 예시">{EXAMPLES.map(e =>
        <button key={e} type="button" onClick={() => fill(e)} disabled={blocked}>{e}<span aria-hidden="true">↗</span></button>)}</div>}
      <p id="chat-help" className="sr-only">Enter로 보내고 Shift + Enter로 줄을 바꿔요</p>
    </div>

    {docOpen && <Drawer title="서류 사진으로 질문하기" description="읽은 값을 확인한 뒤 입력창에 넣어요." onClose={() => setDocOpen(false)}>
      <DocumentPanel heading={false} onApply={applyDocument} onClose={() => setDocOpen(false)} disabled={loading || blocked}/>
    </Drawer>}

    {/* body로 뺀다. 입력창이 화면 밖으로 밀렸을 때(휴대폰 상세 시트가 올라온 경우 등) 돌아가는 길 */}
    {away && !docOpen && !typing && createPortal(<button type="button" className="back-to-composer" onClick={goToComposer}><Sparkles size={15}/>AI에게 이어서 물어보기<span aria-hidden="true">↑</span></button>, document.body)}
  </section>;
}

/** 답을 기다리는 동안의 표시. 단계는 서버가 알린 것만, 시간은 브라우저가 실제로 잰 값이다 (chat-progress.md AC-04).
 * 마지막으로 받은 단계가 진행 중이고, 그 앞은 다음 단계가 시작됐으니 끝난 것이다. 앞으로 올 단계는 미리 그리지 않는다. */
function Pending({stages, since}: {stages: ProgressStage[]; since: number}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(id); }, []);
  const seconds = Math.max(0, Math.floor((now - since) / 1000));
  return <div className="pending-card">
    <div className="pending-head">
      <strong>답을 준비하고 있어요</strong><span className="pending-dots" aria-hidden="true"><i/><i/><i/></span>
      <span className="mono pending-time">{seconds}초</span>
    </div>
    {stages.length > 0
      ? <ol className="pending-steps" aria-live="polite" aria-label="답변 준비 단계">{stages.map((s, i) => {
          const done = i < stages.length - 1;
          return <li key={s} className={done ? 'done' : 'current'}>
            <span className="step-icon">{done ? <Check size={16}/> : <LoaderCircle size={16} className="spin"/>}</span>
            <span className="step-name">{stageLabels[s]}</span><span className="step-state">{done ? '완료' : '진행 중'}</span></li>;
        })}</ol>
      : <p className="pending-note" role="status">{isLive ? '진행 단계를 불러오는 중이에요.' : '체험 모드에서는 진행 단계를 보여 드리지 않아요.'}</p>}
    {/* 답이 올 자리를 흐릿한 줄로 먼저 잡아 둔다. 실제로 기다리는 동안만 보인다 */}
    <div className="pending-skeleton" aria-hidden="true"><span/><span/><span/></div>
  </div>;
}
