'use client';
/** 문장 입력창 (docs/specs/chat-search.md). "내 화물" 화면의 검색 폼(B/L·구분·판매 예정일·예시 메뉴)을 대신한다.
 * 문장은 POST /api/chat으로 가고, 서버가 B/L을 가린 뒤 LLM이 의도(화물 조회·후속 질문·입항 선박 검색)를 고른다.
 * 서류 사진 버튼은 남긴다: 읽은 B/L을 문장에 넣어 주고, 항차·입항 예정일은 되묻기 화면에 미리 채운다.
 */
import {useEffect, useRef, useState, type FormEvent, type KeyboardEvent} from 'react';
import {ArrowUp, Camera, Check, LoaderCircle, Sparkles} from 'lucide-react';
import {useApp} from './AppProvider';
import {DocumentPanel, type DocumentValues} from './DocumentPanel';
import {isLive} from '@/lib/api';

const MAX = 500;  // routers/chat.py ChatRequest.message max_length

/** 처음 보는 사람을 위한 예시 문장. 실제 모드는 누구나 바로 결과를 볼 수 있는 입항 선박 검색만 둔다
 * (데모 B/L을 실제 사용자에게 보여 주지 않는다, 10-01). 데모 모드는 가공 B/L */
const EXAMPLES = isLive
  ? ['이번 주 일본에서 부산 들어오는 배 보여줘', '상하이에서 출발해서 부산 오는 배 있어?', '2주 안에 베트남에서 들어오는 배 알려줘', '3일 안에 부산 들어오는 배 전부']
  : ['MRVDEMO1101 화물 괜찮아?', 'MRVDEMO1107 지금 조치해야 해?', '중국에서 부산 들어오는 배 보여줘'];

export function ChatBar() {
  const {ask, loading, stage, thread, result, request, setDocHints} = useApp();
  const [text, setText] = useState('');
  const [docOpen, setDocOpen] = useState(false);
  const threadRef = useRef<HTMLOListElement>(null);
  const stick = useRef(true);  // 맨 아래를 보고 있으면 true. 위로 올려 읽는 중에는 새 메시지가 와도 끌어내리지 않는다

  // 새 메시지·답 대기 표시가 생기면 맨 아래로 (위 대화를 읽는 중이면 그대로)
  useEffect(() => {
    const el = threadRef.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [thread, loading]);
  function onScroll() {
    const el = threadRef.current;
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  function send(message: string) {
    const m = message.trim();
    if (!m || loading || m.length > MAX) return;
    setText('');
    stick.current = true;  // 내가 보낸 것은 항상 보이게
    void ask(m);
  }
  function submit(e: FormEvent) { e.preventDefault(); send(text); }
  // Enter로 보내고, Shift+Enter는 줄바꿈 (한글 조합 중 Enter는 무시)
  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(text); }
  }
  function applyDocument(v: DocumentValues) {
    setDocOpen(false);
    // MRN이 있으면 문장에 같이 넣는다. 서버가 코드로 뽑아 세관 미등록 때 배를 찾는다 (LLM에는 안 감)
    setText(t => `${v.bl_no}${v.mrn ? ` MRN ${v.mrn}` : ''} ${t}`.trim());
    setDocHints(v.voyage_no || v.forwarder_eta ? {voyage_no: v.voyage_no, forwarder_eta: v.forwarder_eta} : null);
  }


  return <section className="query-section chat-section" aria-label="화물에 대해 묻기">
    {thread.length > 0 && <ol className="chat-thread" ref={threadRef} onScroll={onScroll} aria-live="polite" aria-label="대화" tabIndex={0}>
      {thread.map((t, i) => <li key={i} className={`chat-turn ${t.role}`}>
        {t.role === 'assistant' && <span className="chat-avatar"><Sparkles size={12}/></span>}<p>{t.text}</p></li>)}
      {loading && <li className="chat-turn assistant pending"><span className="chat-avatar"><Sparkles size={12}/></span><p>확인하고 있어요<span className="dots">…</span></p></li>}
    </ol>}
    <form className="chat-form" onSubmit={submit}>
      <label htmlFor="chat-input" className="sr-only">무엇이든 물어보세요</label>
      <textarea id="chat-input" value={text} onChange={e => setText(e.target.value)} onKeyDown={onKey} rows={2} maxLength={MAX}
        placeholder={result && request.bl_no ? '이 화물에 대해 묻거나, 다른 B/L·입항 선박을 물어보세요' : 'B/L 번호와 함께 물어보세요. 예: 내 B/L 번호 + 화물 괜찮아? / 일본에서 부산 오는 배 보여줘'}
        disabled={loading} autoComplete="off" spellCheck={false}/>
      <div className="chat-tools">
        <button type="button" className="doc-trigger" onClick={() => setDocOpen(o => !o)} aria-expanded={docOpen} disabled={loading}><Camera size={13}/>서류 사진</button>
        <span className="mono chat-count">{text.length}/{MAX}</span>
        <button type="submit" className="button primary chat-send" disabled={loading || !text.trim()} aria-label="보내기">
          {loading ? <LoaderCircle size={17} className="spin"/> : <ArrowUp size={17}/>}</button>
      </div>
    </form>
    {!thread.length && <div className="chat-examples" aria-label="예시 문장">{EXAMPLES.map(e =>
      <button key={e} type="button" onClick={() => send(e)} disabled={loading}>{e}</button>)}</div>}
    {docOpen && <DocumentPanel onApply={applyDocument} onClose={() => setDocOpen(false)} disabled={loading}/>}
    {/* 진행 단계는 화면 타이머다. 서버는 진행 이벤트를 보내지 않는다 */}
    {loading && <ol className="progress-steps" aria-label="처리 진행" aria-live="polite">{['이해', '조회', '정리'].map((s, i) =>
      <li key={s} className={i === stage ? 'current' : i < stage ? 'complete' : ''}>{i < stage ? <Check size={14}/> : <span>{i + 1}</span>}{s}</li>)}</ol>}
  </section>;
}
