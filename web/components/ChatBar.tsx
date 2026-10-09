'use client';
/** AI 입력창 (docs/specs/chat-search.md). 홈 화면의 주 기능이라 가운데 넓은 자리에 둔다 (강사 피드백, 구현작업서 4절).
 * 문장은 POST /api/chat/stream으로 가고, 서버가 B/L을 가린 뒤 LLM이 의도(화물 조회·후속 질문·입항 선박 검색)를 고른다.
 * 기다리는 동안은 서버가 알린 실제 처리 단계만 보인다 (docs/specs/chat-progress.md). 타이머로 단계를 만들지 않는다.
 * 서류 첨부: 클립 버튼이나 끌어 놓기로 파일을 붙이면 입력창 위에 파일 칩만 생긴다. 붙이는 순간에는 아무 일도 없다(읽기도 조회도 안 한다).
 * 보내기(버튼·Enter)를 누르면 그때 서류에서 B/L(과 MRN)만 코드로 읽고(POST /api/document/bl, LLM 없음) 곧바로 채팅 조회를 보낸다.
 * 입력창은 셋 다 된다: 사진만(글 없이), 사진 + 글, 글만(전과 같음). 말풍선에는 쓴 글과 파일 이름만 보이고 B/L은 보이지 않는다.
 * 번호를 못 찾으면 조회하지 않고 안내만 한다. 칩과 쓴 글은 그대로 두어 번호를 적어 다시 보낼 수 있다.
 * 읽은 값을 확인하는 카드·수정 화면은 없다(조회가 UNI-PASS 등에서 정확한 값을 가져오므로 선박·항차·날짜는 필요 없다).
 * 화면을 내려 입력창이 안 보이면 "AI에게 이어서 물어보기" 버튼이 나타나 입력창으로 돌려보낸다.
 */
import Link from 'next/link';
import {useEffect, useId, useRef, useState, type DragEvent, type FormEvent, type KeyboardEvent, type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {ArrowRight, FileText, LoaderCircle, Paperclip, Sparkles, X} from 'lucide-react';
import {verdictLabels} from '@/lib/format';
import {useApp} from './AppProvider';
import {EvidencePopover} from './EvidencePopover';
import {ConversationEvidence} from './ConversationEvidence';
import {ChatMiniMap} from './ChatMiniMap';
import {ChatVesselTable} from './ChatVesselTable';
import {ChatCargoTable} from './ChatCargoTable';
import {WatchOfferAction} from './WatchOfferAction';
import {ChatCandidateChips} from './ChatCandidateChips';
import {isLive, QUOTA_MESSAGE, readDocumentBl} from '@/lib/api';
import {onComposerRequest} from '@/lib/composer';
import {stageLabels, type ProgressStage} from '@/lib/progress';

const MAX = 500;  // routers/chat.py ChatRequest.message max_length
const DOC_NO_BL_NOTE = '서류에서 B/L 번호를 찾지 못했어요. 번호를 직접 입력해 주세요.';
const DOC_MAX_BYTES = 10 * 1024 * 1024;  // routers/document.py MAX_BYTES. 서버가 최종 판단하고, 여기서는 올리기 전에 빨리 알려 주는 용도다

/** 처음 보는 사람을 위한 예시 문장. 누르면 입력창에 채우기만 한다(보내기는 사용자가). 실제 모드는 누구나 바로 결과를 볼 수 있는
 * 입항 선박 검색만 둔다 (데모 B/L을 실제 사용자에게 보여 주지 않는다). 데모 모드는 가공 B/L */
const EXAMPLES = isLive
  ? ['이번 주 일본에서 부산 들어오는 배 보여줘', '상하이에서 출발해서 부산 오는 배 있어?', '2주 안에 베트남에서 들어오는 배 알려줘', '3일 안에 부산 들어오는 배 전부']
  : ['MRVDEMO1101 화물 괜찮아?', 'MRVDEMO1107 지금 조치해야 해?', '중국에서 부산 들어오는 배 보여줘'];

/** 사용자가 움직임 줄이기를 켰으면 부드러운 스크롤을 쓰지 않는다 (MDN prefers-reduced-motion) */
function scrollBehavior(): ScrollBehavior {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
}

/** 답 글 속 http(s) 주소를 누를 수 있는 링크로 바꾼다. 단 코드가 붙인 줄만이다 (LLM 문장 속 주소까지 링크가 되어,
 * 도구 결과·서류 글에 심은 주소가 답에 옮겨지면 누를 수 있는 링크로 보였다). 링크로 만드는 줄은 머리가 아래인 줄뿐이다:
 *   "확인처: ...", "진행 상황 직접 보기: ..."  services/referrals.py, 문구 원본은 skills/referrals/rules.md
 * 그 밖의 줄의 주소는 글자 그대로 둔다. 링크도 http·https만 만들고 새 탭으로 연다(noopener: 열린 쪽이 이 창을 못 건드리게).
 * 닫는 괄호는 주소에 넣지 않는다: "(https://...)"의 ")"가 주소 끝에 붙지 않게 (웹 참고 링크가 안 눌림) */
const URL_PATTERN = /(https?:\/\/[^\s)]+)/g;
// [제목](주소) 마크다운 링크: 제목만 보이고 주소는 숨긴다. 제목 속 대괄호·주소 속 공백·괄호는 받지 않는다
const MD_LINK_PATTERN = /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+|\/[a-z][a-z0-9\-/]*)\)/g;  // 사이트 안 경로(/watch)도 받는다: 감시 화물 링크
const LINK_LINE_PREFIXES = ['확인처: ', '진행 상황 직접 보기: ', '감시 화물에서 보기: '];
function linkifyLine(line: string, key: number) {
  if (!LINK_LINE_PREFIXES.some(prefix => line.trimStart().startsWith(prefix))) return line;
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of line.matchAll(MD_LINK_PATTERN)) {
    const at = m.index ?? 0;
    if (at > last) out.push(...bareUrls(line.slice(last, at), `${key}-${at}`));
    // 사이트 안 경로는 같은 탭에서 앱 안 이동(상태 유지), 바깥 주소는 새 탭. 배포 기본 경로는 next.config에 없어 경로 그대로 쓴다 (Shell의 메뉴 링크와 같다)
    out.push(m[2].startsWith('/') ? <Link key={`${key}-md-${at}`} href={m[2]} className="chat-link">{m[1]}</Link>
      : <a key={`${key}-md-${at}`} href={m[2]} target="_blank" rel="noopener noreferrer" className="chat-link">{m[1]}</a>);
    last = at + m[0].length;
  }
  if (last < line.length) out.push(...bareUrls(line.slice(last), `${key}-end`));
  return out;
}
/** 마크다운이 아닌 맨 주소는 예전처럼 주소 글자 그대로 링크로 만든다 (대체 경로) */
function bareUrls(text: string, key: string): ReactNode[] {
  return text.split(URL_PATTERN).map((part, i) =>
    i % 2 === 1 ? <a key={`${key}-${i}`} href={part} target="_blank" rel="noopener noreferrer" className="chat-link">{part}</a> : part);
}
function linkify(text: string): ReactNode[] {
  // 줄마다 따로 본다. 줄바꿈 글자는 그대로 둔다(말풍선은 white-space로 줄을 보인다)
  return text.split('\n').flatMap((line, i) => {
    const parts = linkifyLine(line, i);
    return [...(i === 0 ? [] : ['\n']), ...(Array.isArray(parts) ? parts : [parts])];
  });
}

export function ChatBar({idle = false, onShowDetail}: {idle?: boolean; onShowDetail?: () => void}) {
  const {ask, loading, stages, pendingSince, thread, result, request, usage, view} = useApp();
  // 판정 배지·할 일 한 줄은 "가장 최근 화물 답" 말풍선에만 붙인다. ChatTurn에는 판정이 없어 지금 보는 result(가장 최근 화물 답)에서 읽는다. 지어내지 않는다.
  // B/L 여러 개를 비교한 답은 표가 줄마다 배지를 가지고 있어 붙이지 않는다
  const verdictTurn = view === 'cargo' && result?.verdict ? thread.map((t, i) => t.role === 'assistant' && t.kind === 'cargo' && !(t.cargos && t.cargos.length > 1) ? i : -1).reduce((a, b) => Math.max(a, b), -1) : -1;
  // 선박 후보 칩은 "가장 최근 되묻기 답"에만 붙이고, 그 되묻기가 아직 풀리지 않았을 때만 보인다 (결과 칸이 같은 되묻기 그대로일 때).
  // 후보를 골라 판정이 나오면 결과가 바뀌어 칩이 사라진다
  // 선박 검색 답 중 가장 최근 것만 "나머지 N척 전체 보기"가 열린다 (ChatVesselTable)
  const lastVesselTurn = thread.reduce((a, t, i) => t.role === 'assistant' && t.kind === 'vessels' ? i : a, -1);
  const chipTurn = result?.status === 'insufficient' ? thread.map((t, i) => t.role === 'assistant' && t.agent?.vessel_candidates.length ? i : -1).reduce((a, b) => Math.max(a, b), -1) : -1;
  // 화물 카드가 실제로 보일 때만 "이 화물"로 안내한다. AppProvider.ask도 같은 조건으로 화물을 함께 보낸다 (UI 점검 F5)
  const cargoShown = view === 'cargo' && !!result && !!request.bl_no;
  // 하루 토큰 한도를 다 쓰면 입력·서류 사진을 막는다. 서버도 429로 막는다 (docs/specs/token-quota.md)
  const blocked = !!usage?.exhausted;
  const [text, setText] = useState('');
  // 첨부한 서류. 칩만 만들고 보내기 전에는 읽지 않는다
  const [file, setFile] = useState<File | null>(null);
  const [docBusy, setDocBusy] = useState(false);  // 보낸 뒤 서류에서 B/L을 찾는 동안
  const [docSeconds, setDocSeconds] = useState(0);
  const [docNote, setDocNote] = useState('');  // 형식·크기 안내, B/L 못 찾음 안내
  const pickRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const dragDepth = useRef(0);  // 안쪽 요소를 넘나들 때 dragleave가 먼저 와서 안내가 깜빡이지 않게 센다
  const [away, setAway] = useState(false);  // 입력창이 화면 밖이면 true
  // 다른 입력칸에 글을 쓰는 중이면 true. 휴대폰에서 떠 있는 "이어서 물어보기" 버튼이 입력칸을 덮지 않게 그동안 숨긴다 (F18)
  const [typing, setTyping] = useState(false);
  // 입력창에 이미 글이 있을 때 예시·카드가 채우려던 문장. 덮어쓰지 않고 바꿀지 묻는다 (F11)
  const [offer, setOffer] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);  // 맨 아래를 보고 있으면 true. 위로 올려 읽는 중에는 새 메시지가 와도 끌어내리지 않는다

  // B/L 찾는 동안 브라우저가 실제로 잰 경과 초만 칩에 보인다
  useEffect(() => {
    if (!docBusy) { setDocSeconds(0); return; }
    const start = Date.now();
    const id = setInterval(() => setDocSeconds(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
  }, [docBusy]);

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
    if (loading || blocked || docBusy) return;  // 보내는 중(서류 읽는 중 포함)이거나 한도를 다 썼으면 보내지 않는다
    const m = message.trim();
    if (file) { await sendWithDocument(file, m); return; }
    if (!m || m.length > MAX) return;
    setText('');
    stick.current = true;  // 내가 보낸 것은 항상 보이게
    const ok = await ask(m);
    // 실패하면 쓴 문장을 돌려준다. 그 사이 새로 쓴 글자가 있으면 덮지 않는다
    if (!ok) setText(t => t || m);
  }
  /** 서류를 붙여 보낼 때: 서류에서 B/L(과 MRN)만 코드로 읽고, 쓴 글과 함께 채팅 조회로 보낸다.
   * 사진만(글 없음)도 된다. 문장 = "B/L [MRN 값] 쓴 글": MRN은 서버가 문장에서 코드로 뽑아 세관 미등록 때 배를 찾는다(LLM에는 안 감).
   * 말풍선에는 B/L 대신 쓴 글과 파일 이름만 둔다. 서류 확인·수정 단계는 없고, 선박·항차·날짜는 조회가 가져온다 */
  async function sendWithDocument(f: File, typed: string) {
    setDocNote(''); setDocBusy(true);
    let found;
    try { found = await readDocumentBl(f); }
    catch (e) { setDocNote(e instanceof Error ? e.message : '서류를 읽지 못했어요. 다시 시도해 주세요.'); return; }
    finally { setDocBusy(false); }
    if (!found.bl_no) { setDocNote(DOC_NO_BL_NOTE); return; }  // 조회를 보내지 않는다. 칩과 쓴 글은 그대로 둔다
    const message = [found.bl_no, found.mrn ? `MRN ${found.mrn}` : '', typed].filter(Boolean).join(' ');
    if (message.length > MAX) { setDocNote(`설명이 너무 길어요. 서류 번호와 합쳐 ${MAX}자 이하로 줄여 주세요.`); return; }
    const display = [typed, `첨부: ${f.name}`].filter(Boolean).join('\n');
    setText('');
    stick.current = true;
    const ok = await ask(message, {document: null, display});
    // 성공하면 서류를 뗀다. 실패하면 칩과 쓴 글을 돌려 다시 보낼 수 있게 한다
    if (ok) removeDoc(); else setText(t => t || typed);
  }
  function submit(e: FormEvent) { e.preventDefault(); void send(text); }
  // Enter로 보내고, Shift+Enter는 줄바꿈 (한글 조합 중 Enter는 무시)
  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(text); }
  }
  function fill(example: string) { if (blocked) return; offerText(example); inputRef.current?.focus(); }
  function removeDoc() { setFile(null); setDocNote(''); }

  /** 파일을 첨부한다 (클립 버튼, 끌어 놓기 공통). 종류·크기는 올리기 전에 한 번 걸러 주고, 최종 검사는 서버(POST /api/document)가 한다 */
  function attach(f: File | undefined) {
    if (!f || loading || blocked) return;
    if (docBusy) return;
    if (!(f.type.startsWith('image/') || f.type === 'application/pdf' || /\.pdf$/i.test(f.name))) { setDocNote('JPG, PNG, PDF 파일만 올릴 수 있어요.'); return; }
    if (f.size > DOC_MAX_BYTES) { setDocNote('파일은 10MB 이하만 올릴 수 있어요.'); return; }
    setDocNote(''); setFile(f);
    requestAnimationFrame(() => inputRef.current?.focus());  // 바로 설명을 쓸 수 있게
  }
  function openPicker() { if (!loading && !blocked) pickRef.current?.click(); }

  // 끌어 놓기: 채팅 영역 어디든 놓을 수 있다. 파일이 아닌 끌기(글자 등)는 건드리지 않는다.
  // 막힌 상태에서도 놓은 파일을 브라우저가 열어 버리지 않게 preventDefault는 늘 한다. 안내 화면만 막는다
  const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes('Files');
  const canDrop = !loading && !blocked;
  function onDragEnter(e: DragEvent) { if (!hasFiles(e)) return; e.preventDefault(); dragDepth.current += 1; if (canDrop) setDragOver(true); }
  function onDragOver(e: DragEvent) { if (!hasFiles(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = canDrop ? 'copy' : 'none'; }
  function onDragLeave(e: DragEvent) { if (!hasFiles(e)) return; dragDepth.current = Math.max(0, dragDepth.current - 1); if (dragDepth.current === 0) setDragOver(false); }
  function onDropFile(e: DragEvent) {
    if (!hasFiles(e)) return;
    e.preventDefault(); dragDepth.current = 0; setDragOver(false);
    if (canDrop) attach(e.dataTransfer.files[0]);
  }

  // 판정 답 말풍선 안의 배지·할 일 한 줄. 대화가 비어 있는데 결과만 있는 경우(데모 첫 화면, 저장된 판정 열기)도 같은 모양으로 그린다 (시안 2-2)
  const verdictBlock = result?.verdict ? <div className="chat-verdict">
    <p className={`chat-grade ${result.verdict}`}><i aria-hidden="true"/>{verdictLabels[result.verdict]}</p>
    {result.actions[0] && <p className="chat-todo"><span>지금 할 일</span>{result.actions[0]}</p>}
    <button type="button" className="chat-show-detail" onClick={onShowDetail}>결과 보기</button></div> : null;
  // 대화가 없고 답할 글만 있는 첫 화면(.chat-seed는 .chat-turn이 아니다: 실제 주고받은 말만 .chat-turn으로 센다): 결과 칸의 answer를 그대로 답 말풍선으로 보인다 (지어내지 않는다, 서버 값)
  const seedAnswer = thread.length === 0 && view === 'cargo' && result && result.status !== 'insufficient' && result.answer ? result : null;
  const empty = idle && !loading && thread.length === 0;
  // 이 대화의 근거 모음: 답 턴마다 붙은 근거를 순번(turn)과 함께 모은다. 0개면 버튼이 숨는다
  const convEvidence = thread.flatMap((t, i) => t.role === 'assistant' && t.evidence ? t.evidence.map(e => ({...e, turn: i})) : []);

  return <section className="ask" aria-label="AI에게 묻기" onDragEnter={onDragEnter} onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDropFile}>
    {dragOver && <div className="doc-drop-overlay" aria-hidden="true"><Paperclip size={28} strokeWidth={1.5}/><strong>여기에 놓으세요</strong><span>JPG·PNG·PDF, 10MB 이하</span></div>}
    {/* 대화는 이 칸 안에서만 스크롤하고, 입력창은 아래에 고정한다 (시안 2-1·2-2). 페이지 전체는 움직이지 않는다 */}
    <div className="chat-scroll" ref={threadRef} onScroll={onScroll} role="log" aria-label="대화" tabIndex={0}>
      {convEvidence.length > 0 && <div className="chat-evidence-bar"><ConversationEvidence evidence={convEvidence}/></div>}
      {empty ? <div className="chat-empty">
        <span className="chat-eyebrow">Marvia</span>
        <h2>어떤 화물을 확인할까요?</h2>
        <div className="feature-tiles">
          <button type="button" onClick={() => isLive ? goToComposer() : fill(EXAMPLES[0])} disabled={blocked}><span className="tile-no">01</span>B/L 번호로 조회하기</button>
          <button type="button" onClick={() => fill(isLive ? EXAMPLES[0] : EXAMPLES[2])} disabled={blocked}><span className="tile-no">02</span>입항 예정 선박 찾기</button>
          <button type="button" onClick={openPicker} disabled={blocked}><span className="tile-no">03</span>서류 사진 올리기</button>
        </div>
      </div> : <ol className="chat-thread" aria-live="polite">
        {thread.map((t, i) => <li key={i} className={`chat-turn ${t.role}`}>
          <div className="chat-body"><div className="chat-bubble">{t.role === 'assistant' && t.kind === 'vessels' && t.shipList ? <ChatVesselTable text={t.text} list={t.shipList} evidence={t.evidence ?? []} citations={t.citations ?? []} renderText={linkify} latest={i === lastVesselTurn}/> : <p>{t.role === 'assistant' ? <EvidencePopover text={t.text} citations={t.citations ?? []} evidence={t.evidence ?? []} renderText={linkify}/> : t.text}</p>}{i === verdictTurn && verdictBlock}</div>{t.role === 'assistant' && t.cargos && t.cargos.length > 1 ? <ChatCargoTable cargos={t.cargos}/> : t.role === 'assistant' && t.map && <ChatMiniMap map={t.map}/>}{t.role === 'assistant' && t.steps && t.steps.length > 0 && <StepsSummary steps={t.steps} tookMs={t.tookMs ?? 0}/>}{t.role === 'assistant' && t.watchOffer && <WatchOfferAction offer={t.watchOffer}/>}{i === chipTurn && t.agent && t.request && t.agent.trace_id === result?.trace_id && <ChatCandidateChips agent={t.agent} request={t.request} disabled={loading || blocked}/>}</div></li>)}
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
      {docNote && <p role="alert" className="request-error doc-note">{docNote}</p>}
      {/* 파일 칩. 보내는 동안(채팅 진행 표시가 대신 보인다)은 숨기기만 하고 상태는 지킨다(실패하면 그대로 다시 보인다) */}
      {file && <div className="doc-attach" hidden={loading && !docBusy}><div className="doc-chip" role="status">
        {docBusy ? <LoaderCircle size={16} className="spin" aria-hidden="true"/> : <FileText size={16} strokeWidth={1.75} aria-hidden="true"/>}
        <span className="doc-chip-name">{file.name}</span>
        <span className="doc-chip-state">{docBusy ? <>서류에서 B/L 찾는 중 · <span className="mono">{docSeconds}초</span></> : '보내기를 누르면 서류에서 B/L을 찾아 조회해요'}</span>
        <button type="button" className="icon-button doc-chip-x" onClick={removeDoc} disabled={docBusy} aria-label="첨부한 서류 빼기"><X size={16}/></button>
      </div></div>}
      <div className="composer-wrap" ref={wrapRef}>
        <form className="composer" onSubmit={submit}>
          <label htmlFor="chat-input" className="sr-only">Marvia에게 질문하기</label>
          <textarea id="chat-input" ref={inputRef} value={text} onChange={e => setText(e.target.value)} onKeyDown={onKey} rows={1} maxLength={MAX} disabled={blocked}
            placeholder={file ? '서류와 함께 보낼 설명을 적어 주세요 (선택, 사진만 보내도 돼요)' : cargoShown ? '이 화물에 대해 더 물어보세요' : 'B/L 번호나 궁금한 점을 입력해 주세요'}
            aria-describedby="chat-help" autoComplete="off" spellCheck={false}/>
          <div className="composer-foot">
            {/* 서류 첨부는 클립 아이콘 하나. 옆 패널을 열지 않고 파일 선택창만 연다 */}
            <button type="button" className="doc-trigger attach-btn" onClick={openPicker} disabled={loading || blocked} aria-label="서류 사진·PDF 첨부" title="서류 사진·PDF 첨부"><Paperclip size={18} strokeWidth={1.5}/></button>
            <input ref={pickRef} type="file" accept="image/*,application/pdf" className="sr-only" tabIndex={-1} aria-hidden="true"
              onChange={e => { attach(e.target.files?.[0]); e.target.value = ''; }}/>
            <div className="composer-send">
              {/* 글자 수는 쓰기 시작한 뒤에만 보인다. 빈 입력창에 숫자를 늘 두면 어수선하다 */}
              {text.length > 0 && <span className="mono chat-count" aria-label={`${text.length}자 입력, 최대 ${MAX}자`}>{text.length} / {MAX}</span>}
              <button type="submit" className="send" disabled={loading || blocked || docBusy || (!file && !text.trim())} aria-label="AI에게 질문 보내기">
                {loading || docBusy ? <LoaderCircle size={20} strokeWidth={1.5} className="spin"/> : <ArrowRight size={20} strokeWidth={1.5}/>}</button>
            </div>
          </div>
        </form>
      </div>
      {/* 시작 문장: 대화가 비어 있을 때만. 누르면 입력창에 채우기만 한다 */}
      {empty && <div className="chat-examples" aria-label="질문 예시">{EXAMPLES.map(e =>
        <button key={e} type="button" onClick={() => fill(e)} disabled={blocked}>{e}<span aria-hidden="true">↗</span></button>)}</div>}
      <p id="chat-help" className="sr-only">Enter로 보내고 Shift + Enter로 줄을 바꿔요</p>
    </div>

    {/* body로 뺀다. 입력창이 화면 밖으로 밀렸을 때(휴대폰 상세 시트가 올라온 경우 등) 돌아가는 길 */}
    {away && !typing && createPortal(<button type="button" className="back-to-composer" onClick={goToComposer}><Sparkles size={15}/>AI에게 이어서 물어보기<span aria-hidden="true">↑</span></button>, document.body)}
  </section>;
}

/** 답을 기다리는 동안의 표시. 단계는 서버가 알린 것만, 시간은 브라우저가 실제로 잰 값이다 (chat-progress.md AC-04).
 * 마지막으로 받은 단계가 진행 중이고, 그 앞은 다음 단계가 시작됐으니 끝난 것이다. 앞으로 올 단계는 미리 그리지 않는다. */
function Pending({stages, since}: {stages: ProgressStage[]; since: number}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(id); }, []);
  // 단계별 경과 시간: 브라우저가 단계를 처음 본 시각만 잰다 (서버가 단계별 시간을 주지 않는다. 지어내지 않는다)
  const seenAt = useRef(new Map<ProgressStage, number>());
  for (const s of stages) if (!seenAt.current.has(s)) seenAt.current.set(s, Date.now());
  const seconds = Math.max(0, Math.floor((now - since) / 1000));
  return <div className="pending-card">
    <div className="pending-head">
      <span>답을 준비하고 있어요</span><span className="pending-dots" aria-hidden="true"><i/><i/><i/></span>
      <span className="mono pending-time">{seconds}초</span>
    </div>
    {stages.length > 0
      // 세로 타임라인. li 글자는 "단계 이름 + 완료/진행 중"만 둔다: 경과 시간은 CSS ::after로 그린다 (e2e가 글자 끝을 본다)
      ? <ol className="pending-steps" aria-live="polite" aria-label="답변 준비 단계">{stages.map((s, i) => {
          const done = i < stages.length - 1;
          const start = seenAt.current.get(s) ?? now;
          return <li key={s} className={done ? 'done' : 'current'} data-elapsed={done ? undefined : `${Math.max(0, Math.floor((now - start) / 1000))}초`}>
            <span className="step-icon" aria-hidden="true"/>
            <span className="step-name">{stageLabels[s]}</span><span className="step-state">{done ? '완료' : '진행 중'}</span></li>;
        })}</ol>
      : <p className="pending-note" role="status">{isLive ? '진행 단계를 불러오는 중이에요.' : '체험 모드에서는 진행 단계를 보여 드리지 않아요.'}</p>}
    {/* 답이 올 자리를 흐릿한 줄로 먼저 잡아 둔다. 실제로 기다리는 동안만 보인다 */}
    <div className="pending-skeleton" aria-hidden="true"><span/><span/><span/></div>
  </div>;
}

/** 답이 온 뒤 접힌 한 줄 요약 "N단계 · M초". 누르면 같은 타임라인이 모두 완료로 펼쳐진다.
 * 단계 시간은 브라우저가 처음 본 시각 차이다. 마지막 단계는 답이 온 시각까지로 잰다 */
function StepsSummary({steps, tookMs}: {steps: {stage: ProgressStage; at: number}[]; tookMs: number}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return <div className="steps-summary">
    <button type="button" className="steps-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen(o => !o)}>
      {steps.length}단계 · {Math.max(1, Math.round(tookMs / 1000))}초<span aria-hidden="true">{open ? '▾' : '▸'}</span></button>
    {open && <ol id={id} className="pending-steps settled" aria-label="답변 준비 단계">{steps.map(s =>
      <li key={s.stage} className="done"><span className="step-icon" aria-hidden="true"/><span className="step-name">{stageLabels[s.stage]}</span><span className="step-state">완료</span></li>)}</ol>}
  </div>;
}
