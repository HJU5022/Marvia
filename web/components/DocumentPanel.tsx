'use client';
/** 서류 사진으로 입력 채우기 (작업 E2 "서류 사진", docs/specs/document-extract.md).
 *
 * 흐름: 사진 올리기 → POST /api/document → 7칸 확인 화면 → 사용자가 고친 값만 폼에 넣는다.
 * 읽은 값으로 바로 조회하지 않는다 (Spec "사용자 확인 화면", SDD 비전 울타리). 검사에 걸린 칸은 "확인 필요"로 드러낸다.
 * B/L은 조회 폼에 바로 넣고, 항차·입항 예정일은 되묻기 화면(CandidatePicker)에 미리 채울 값으로만 둔다.
 * 첫 조회에 섞어 보내면 백엔드가 되묻기 답으로 읽기 때문이다 (schemas/agent.py "선택 칸으로 첫 조회/되묻기 답 구분").
 * 출항일(etd, 10-06): 사용자가 확인한 값만 DocHints로 넘기고, 조회 때 서버가 내 화물 현황 표 출항 칸에 적는다(source 'document').
 * 판정에는 쓰이지 않고, 직접 적은 날짜는 덮지 않는다 (services/cargo.upsert_assessment).
 * 품명·선적항·양하항은 확인용으로만 보여 주고 어디에도 보내거나 저장하지 않는다 (CLAUDE.md 품명 비저장).
 *
 * B/L 조건 세 칸·인코텀즈·화물 인도 연락처 (10-02 결정 6·7, docs/specs/memory.md):
 * 사용자가 고르거나 고친 값만 "확인한 값으로 채우기"를 누를 때 POST /api/memory/document-facts로 저장한다.
 * 검사에 걸린 칸은 미리 고르지 않고 비워 둔다(읽은 값은 옆에 보여 준다). 확인 안 한 값이 저장되지 않게 하려는 것이다.
 * 저장은 실제 모드 + 로그인일 때만, 실패해도 입력 채우기는 막지 않는다. 판정 등급에는 쓰지 않는다.
 *
 * 10-08 정운 49·51·53번: 채팅 입력창 클립 버튼·끌어 놓기로 첨부한 파일은 inline 모드로 그린다. 큰 옆 패널과 점선 칸 없이
 * 입력창 위의 파일 칩(이름, 읽는 중 N초, X)과 작은 확인 카드만 보인다. 파일은 올리는 순간 바로 읽기 시작한다(file prop).
 * 확인 카드의 버튼이나 입력창 보내기(handleRef.confirm)가 같은 apply()를 불러 onApply로 값을 넘긴다. 입력창에 쓴 설명을 함께 보내는 일은 ChatBar가 한다.
 * heading·dropzone 모드(기본)는 TopBar의 옛 조회 폼이 그대로 쓴다.
 */
import {useEffect, useId, useRef, useState, type ChangeEvent, type DragEvent, type MutableRefObject} from 'react';
import {Camera, Check, ChevronDown, FileText, LoaderCircle, Pencil, RotateCcw, TriangleAlert, X} from 'lucide-react';
import {isLive, readDocument, saveDocumentFacts} from '@/lib/api';
import type {ContactRole, DocumentCheck, DocumentConditionKey, DocumentFactsRequest, DocumentResponse, FreightTerm, Incoterm, OriginalBl} from '@/lib/types';

/** 화면 순서는 시안(2-5)을 따른다: 한 줄에 셋. 선명·품명은 사용자가 화물을 알아보는 값이라 굵게 보인다 (CARD_STRONG) */
const FIELD_LABELS: [keyof DocumentResponse['fields'], string, string][] = [
  ['bl_no', 'B/L 번호', '조회에 사용'],
  ['vessel', '선박 이름', '확인용'],
  ['voyage', '항차', '배 확인에 사용'],
  ['eta', '입항 예정일', '배 확인에 사용'],
  ['pol', '선적항', '확인용'],
  ['pod', '양하항', '확인용'],
  ['item', '품명', '확인용, 저장 안 함'],
  ['etd', '출항일', '현황 표에 기록'],
];
const CARD_STRONG = new Set(['vessel', 'item']);
/** 검사 이름은 services/doc_ocr.check_fields와 같다. */
const CHECK_LABELS: Record<DocumentCheck, string> = {
  missing: '읽지 못함',
  not_in_text: '서류에서 찾지 못함',
  format: '형식 확인',
  ambiguous: '서류 안에서 값이 서로 다름',
};
const EDITABLE = new Set(['bl_no', 'voyage', 'eta', 'etd']);
/** B/L 조건 고르기 칸. 값은 backend/app/schemas/memory.py, 마이그레이션 015 CHECK와 같다. 빈 값은 "모름" */
const CONDITION_CHOICES: [DocumentConditionKey, string, [string, string][]][] = [
  ['original_bl', '원본 B/L', [['required', '원본 필요'], ['surrendered', '서렌더(원본 없이 가능)']]],
  ['to_order_bank', '수하인', [['true', '은행 지시식(TO ORDER OF 은행)'], ['false', '은행 지시식 아님']]],
  ['freight_term', '운임', [['prepaid', '선불(PREPAID)'], ['collect', '착불(COLLECT)']]],
  ['incoterm', '거래 조건', [['CIF', 'CIF'], ['FOB', 'FOB'], ['CFR', 'CFR']]],
  ['contact_role', '연락처 역할', [['포워더', '포워더'], ['관세사', '관세사'], ['수출자', '수출자'], ['판매처', '판매처']]],
];
/** 연락처 두 칸의 이름. 배너에서 "확인이 필요한 칸"을 이름으로 말하려고 같이 둔다 */
const CONTACT_LABELS: [DocumentConditionKey, string][] = [['contact_company', '연락처 회사'], ['contact_phone', '회사 전화']];
const CONDITION_KEYS: DocumentConditionKey[] = ['original_bl', 'to_order_bank', 'freight_term', 'incoterm', 'contact_company', 'contact_role', 'contact_phone'];

/** 칸 위 오른쪽에 붙는 검사 결과 배지. 걸린 검사만 주의색으로 칸 위에 직접 보인다 (시안 2-5 실수 정정: 칸 밖 작은 글로 두지 않는다).
 * 통과한 칸은 아무것도 붙이지 않아 걸린 칸만 눈에 띈다. 값이 없을 때만 중립 회색 "서류에 없음" */
function CheckBadges({checks, emptyText}: {checks: DocumentCheck[]; emptyText?: string}) {
  if (checks.length) return <>{checks.map(c => <span key={c} className="doc-badge warn"><TriangleAlert size={14} strokeWidth={2}/>{CHECK_LABELS[c]}</span>)}</>;
  return emptyText ? <span className="doc-badge none">{emptyText}</span> : null;
}

export interface DocumentValues { bl_no: string; voyage_no: string | null; forwarder_eta: string | null; mrn: string | null; departed_on: string | null }

/** inline 모드가 부모(ChatBar)에게 알리는 지금 상태. busy=읽는 중, ready=확인 카드가 떠 있음, error=읽기 실패.
 * canApply는 확인 카드의 값이 모두 형식에 맞아 조회해도 되는지다 (보내기 버튼을 켜고 끄는 데 쓴다) */
export interface DocumentPhase { phase: 'idle' | 'busy' | 'ready' | 'error'; canApply: boolean }
/** 입력창의 보내기 버튼이 확인 카드를 대신 눌러 주는 손잡이. 형식이 틀리면 아무것도 보내지 않고 false */
export interface DocumentHandle { confirm: () => boolean }

/** heading=false: 드로어(Drawer)가 제목과 닫기 버튼을 그릴 때. 제목·닫기가 두 번 보이지 않게 한다.
 * inline=true + file(10-08 정운 49번): 채팅 입력창 위에 작게 그리는 모드. file이 오면 바로 읽는다. */
export function DocumentPanel({onApply, onClose, disabled, heading = true, inline = false, file, handleRef, onPhase}: {
  onApply: (v: DocumentValues) => void; onClose: () => void; disabled: boolean; heading?: boolean;
  inline?: boolean; file?: File; handleRef?: MutableRefObject<DocumentHandle | null>; onPhase?: (s: DocumentPhase) => void;
}) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [fileName, setFileName] = useState('');
  const [result, setResult] = useState<DocumentResponse | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [dragging, setDragging] = useState(false);
  // 읽는 데 20~28초쯤 걸려 스피너만으로는 멈춘 것처럼 보인다. 브라우저가 실제로 잰 경과 초만 보인다 (10-07 정운 실사용 11번)
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!busy) { setSeconds(0); return; }
    const start = Date.now();
    const id = setInterval(() => setSeconds(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
  }, [busy]);

  async function upload(file: File | undefined) {
    if (!file || busy) return;
    setBusy(true); setError(''); setResult(null); setFileName(file.name);
    try {
      const r = await readDocument(file);
      setResult(r);
      // 조건·연락처 칸은 검사에 걸리면 미리 채우지 않는다. 사용자가 직접 골라야 저장된다 (10-02 결정 7)
      setValues({...Object.fromEntries(Object.entries(r.fields).map(([k, f]) =>
        [k, (CONDITION_KEYS as string[]).includes(k) && f.checks.length ? '' : f.value ?? ''])), mrn: r.mrn ?? ''});
    } catch (e) {
      setError(e instanceof Error ? e.message : '사진을 읽지 못했어요. 다시 시도해 주세요.');
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';  // 같은 파일을 다시 골라도 change가 나게
    }
  }

  // inline 모드: 부모가 넘긴 파일을 마운트 때 한 번만 읽는다. 개발 모드의 effect 두 번 실행이 OCR·토큰을 두 번 쓰지 않게 ref로 막는다.
  // 다른 파일은 부모가 key를 바꿔 새로 마운트한다
  const started = useRef(false);
  useEffect(() => {
    if (!inline || !file || started.current) return;
    started.current = true;
    void upload(file);
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // 막힌 상태(보내는 중, 하루 AI 사용량 소진)에는 끌어 놓은 사진도 받지 않는다. 고르기 칸만 막으면 끌어 놓기로 새어 나간다 (F7)
  function onDrop(e: DragEvent) { e.preventDefault(); setDragging(false); if (disabled || busy) return; void upload(e.dataTransfer.files[0]); }

  const bl = (values.bl_no ?? '').replace(/\s/g, '').toUpperCase();
  const blValid = /^[A-Z0-9]{8,20}$/.test(bl);  // schemas/agent.py _BL_PATTERN
  const eta = values.eta ?? '';
  const etaValid = !eta || /^\d{4}-\d{2}-\d{2}$/.test(eta);
  const etd = values.etd ?? '';
  const etdValid = !etd || /^\d{4}-\d{2}-\d{2}$/.test(etd);  // 출항일은 비어도 된다 (서류에 없는 경우가 흔하다)
  const mrn = (values.mrn ?? '').replace(/\s/g, '').toUpperCase();
  const mrnValid = !mrn || /^[0-9]{2}[A-Z0-9]{8}[IE]$/.test(mrn);  // schemas/agent.py _MRN_PATTERN

  /** 사용자가 확인한 조건·연락처를 기억에 저장한다. 실제 모드 + 로그인일 때만 보내고(lib/api.ts), 실패는 조용히 넘긴다.
   * 고른 값이 하나도 없으면 보내지 않는다. 거래처는 회사와 역할이 있고 서류 종류(B/L·A/N)를 알 때만 보낸다 */
  function rememberFacts() {
    const v = (k: DocumentConditionKey) => values[k]?.trim() || null;
    const company = v('contact_company'), role = v('contact_role') as ContactRole | null;
    const facts: DocumentFactsRequest = {
      bl_no: bl, source: result?.doc_kind ?? null,
      original_bl: v('original_bl') as OriginalBl | null,
      to_order_bank: v('to_order_bank') === null ? null : v('to_order_bank') === 'true',
      freight_term: v('freight_term') as FreightTerm | null, incoterm: v('incoterm') as Incoterm | null,
      contact: company && role && result?.doc_kind ? {company, role, phone: v('contact_phone')} : null,
    };
    const any = facts.original_bl || facts.to_order_bank !== null || facts.freight_term || facts.incoterm || facts.contact;
    if (any) void saveDocumentFacts(facts).catch(() => { /* 기억 저장 실패는 입력 채우기를 막지 않는다 */ });
  }

  const canApply = blValid && etaValid && etdValid && mrnValid;
  /** 확인한 값을 넘긴다. 반환값은 실제로 넘겼는지 (입력창 보내기가 형식 오류를 알 수 있게) */
  function apply(): boolean {
    if (!canApply) return false;
    rememberFacts();
    // MRN은 세관에 아직 없는 화물을 해수부 입항 신고로 찾을 때 쓴다 (docs/specs/mrn-fallback.md)
    onApply({bl_no: bl, voyage_no: values.voyage?.trim() || null, forwarder_eta: eta || null, mrn: mrnValid ? mrn || null : null, departed_on: etd || null});
    return true;
  }

  // inline 모드: 부모가 보내기 버튼으로 apply를 부를 수 있게 매 렌더 최신 apply를 건넨다 (값 state가 바뀔 때마다 apply가 새로 만들어진다)
  useEffect(() => {
    if (!handleRef) return;
    handleRef.current = {confirm: apply};
    return () => { handleRef.current = null; };
  });
  const phase: DocumentPhase['phase'] = busy ? 'busy' : result ? 'ready' : error ? 'error' : 'idle';
  useEffect(() => { onPhase?.({phase, canApply: !!result && canApply}); }, [phase, result, canApply]);  // eslint-disable-line react-hooks/exhaustive-deps

  // 배너에 "어느 칸을 봐야 하는지" 이름으로 보이려고, 검사에 걸린 칸의 이름을 모은다 (순서는 화면 순서)
  const flaggedNames = result ? [
    ...FIELD_LABELS.map(([k, l]) => [k, l] as const),
    ...CONDITION_CHOICES.map(([k, l]) => [k, l] as const),
    ...CONTACT_LABELS.map(([k, l]) => [k, l] as const),
  ].filter(([k]) => (result.fields[k]?.checks.length ?? 0) > 0).map(([, l]) => l) : [];

  const emptyField = {value: null, checks: [] as DocumentCheck[]};  // etd·조건 칸은 옛 서버 응답에 없을 수 있다

  // B/L 조건·연락처 칸. inline 모드는 접어서, 기본 모드는 그대로 펼쳐서 보인다 (아래 return)
  const conditions = result ? (
      <section className="doc-conditions" aria-labelledby={`${inputId}-cond`}>
        <h3 id={`${inputId}-cond`}>B/L 조건과 화물 인도 연락처</h3>
        <p className="doc-hint-line">고른 값은 기억에만 쓰고, 판정에는 쓰지 않아요</p>
        <div className="doc-cond-grid">
          {CONDITION_CHOICES.map(([key, label, choices]) => {
            const f = result.fields[key] ?? emptyField;
            const id = `${inputId}-${key}`;
            return <div key={key} className={`doc-cond ${f.checks.length ? 'flagged' : ''}`}>
              <div className="doc-cond-top"><label htmlFor={id}>{label}</label>
                <span className="doc-badges"><CheckBadges checks={f.checks} emptyText={!f.value ? '서류에 없음' : undefined}/></span></div>
              <div className="doc-select">
                <select id={id} value={values[key] ?? ''} onChange={e => setValues(v => ({...v, [key]: e.target.value}))} aria-invalid={f.checks.length > 0}>
                  <option value="">모름</option>
                  {choices.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
                </select><ChevronDown size={16} aria-hidden="true"/>
              </div>
              {f.checks.length > 0 && f.value && <small>읽은 값: {choices.find(c => c[0] === f.value)?.[1] ?? f.value}</small>}
            </div>;
          })}
        </div>
        <div className="doc-contact-grid">
          {CONTACT_LABELS.map(([key, label]) => {
            const f = result.fields[key] ?? emptyField;
            const id = `${inputId}-${key}`;
            return <div key={key} className={`doc-cond ${f.checks.length ? 'flagged' : ''}`}>
              <div className="doc-cond-top"><label htmlFor={id}>{label}</label>
                <span className="doc-badges"><CheckBadges checks={f.checks} emptyText={!f.value ? '서류에 없음' : undefined}/></span></div>
              <input id={id} className="doc-text" value={values[key] ?? ''} spellCheck={false} maxLength={key === 'contact_company' ? 40 : 20}
                onChange={e => setValues(v => ({...v, [key]: e.target.value}))} aria-invalid={f.checks.length > 0}/>
              <small>{f.checks.length && f.value ? `읽은 값: ${f.value}` : key === 'contact_company' ? '회사 이름만 입력해요. 개인 이름은 받지 않아요' : '숫자와 하이픈만 입력해요. 개인 휴대폰은 받지 않아요'}</small>
            </div>;
          })}
        </div>
      </section>
  ) : null;

  return <section className={`document-panel ${heading ? '' : 'in-drawer'} ${inline ? 'inline' : ''}`} aria-label={inline ? '첨부한 서류' : '서류 사진으로 채우기'}>
    {!inline && heading && <button type="button" className="icon-button doc-close" onClick={onClose} aria-label="서류 사진 닫기"><X size={18}/></button>}
    {!inline && <header className="doc-title">
      <h2>{result ? '서류에서 읽은 값을 확인해 주세요' : '서류 사진으로 채우기'}</h2>
      {result && <p>확인하거나 고친 값만 조회와 기억에 사용해요.</p>}
    </header>}

    {/* 10-08 정운 53번: 파일 칩. 입력창 위에 두고 X로 뗀다. 읽는 동안은 경과 초만 보인다(예상 시간 문구는 재지 않은 값이라 뺐다) */}
    {inline && <div className="doc-chip" role="status">
      {busy ? <LoaderCircle size={16} className="spin" aria-hidden="true"/> : <FileText size={16} strokeWidth={1.75} aria-hidden="true"/>}
      <span className="doc-chip-name">{fileName || file?.name}</span>
      <span className="doc-chip-state">{busy ? <>서류를 읽는 중 · <span className="mono">{seconds}초</span></> : result ? '읽기 끝' : error ? '읽지 못함' : ''}</span>
      <button type="button" className="icon-button doc-chip-x" onClick={onClose} aria-label="첨부한 서류 빼기"><X size={16}/></button>
    </div>}

    {!inline && !result && <label htmlFor={inputId} className={`dropzone ${dragging ? 'dragging' : ''} ${busy ? 'busy' : ''} ${disabled ? 'disabled' : ''}`} aria-disabled={disabled || undefined}
      onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
      {busy ? <LoaderCircle size={32} className="spin"/> : <Camera size={32} strokeWidth={1.5}/>}
      <strong>{busy ? '서류에서 글자를 읽는 중' : '사진이나 PDF를 끌어 놓거나 눌러서 골라 주세요'}</strong>
      <span>{busy ? fileName : 'JPG·PNG·PDF, 10MB 이하예요. 파일은 저장하지 않아요'}</span>
      {busy && <span className="doc-wait" role="status"><span className="mono">{seconds}초</span></span>}
      <input ref={inputRef} id={inputId} type="file" accept="image/*,application/pdf" className="sr-only" disabled={busy || disabled}
        onChange={(e: ChangeEvent<HTMLInputElement>) => void upload(e.target.files?.[0])}/>
    </label>}

    {error && <p role="alert" className="request-error">{error}</p>}

    {result && <div className="document-result">
      <div className={`document-status ${result.needs_review ? 'review' : 'clear'}`}>
        {result.needs_review ? <TriangleAlert size={20} strokeWidth={1.75} aria-hidden="true"/> : <Check size={20} strokeWidth={2} aria-hidden="true"/>}
        <div>
          <strong>{result.needs_review ? '다 읽었어요. 확인이 필요한 칸이 있어요.' : '다 읽었어요. 모든 칸이 검사를 통과했어요.'}</strong>
          {result.needs_review && flaggedNames.length > 0 && <span className="doc-flagged-names">{flaggedNames.join(' · ')}</span>}
          {result.status === 'partial' && <span>B/L 번호만 읽었어요. 나머지 칸은 직접 확인해 주세요.</span>}
        </div>
      </div>
      {/* 10-06: AI 단계가 실패하면 빈 칸이 서류 탓처럼 보인다. 실패했다고 알리고 사진을 다시 올리게 한다 ("다른 사진" 버튼) */}
      {result.llm_error && <p role="alert" className="request-error">AI가 서류 글자를 정리하지 못했어요. 다시 시도해 주세요.</p>}

      <section className="doc-group" aria-labelledby={`${inputId}-read`}>
      <h3 id={`${inputId}-read`} className="doc-section-title">서류에서 읽은 값</h3>
      <div className="doc-fields">
        {FIELD_LABELS.map(([key, label, use]) => {
          const f = result.fields[key] ?? emptyField;
          const id = `${inputId}-${key}`;
          const editable = EDITABLE.has(key);
          return <div key={key} className={`doc-field ${f.checks.length ? 'flagged' : ''} ${CARD_STRONG.has(key) ? 'strong' : ''}`}>
            <div className="doc-field-top">
              <label htmlFor={id}>{label}<small> · {use}</small></label>
              <span className="doc-badges"><CheckBadges checks={f.checks} emptyText={key === 'etd' && !f.value && !f.checks.length ? '서류에 없음' : undefined}/></span>
            </div>
            {editable
              ? <div className="doc-value"><input id={id} value={values[key] ?? ''} type={key === 'eta' || key === 'etd' ? 'date' : 'text'} spellCheck={false}
                  onChange={e => setValues(v => ({...v, [key]: e.target.value}))} aria-invalid={f.checks.length > 0 || (key === 'bl_no' && !blValid)}/><Pencil size={16} strokeWidth={1.75} aria-hidden="true"/></div>
              : <output id={id} className="doc-value">{f.value ?? '읽지 못함'}</output>}
          </div>;
        })}
        <div className={`doc-field ${values.mrn && !mrnValid ? 'flagged' : ''}`}>
          <div className="doc-field-top"><label htmlFor={`${inputId}-mrn`}>화물관리번호(MRN)<small> · 배 찾기용</small></label>
            <span className="doc-badges">{values.mrn ? (!mrnValid && <span className="doc-badge warn"><TriangleAlert size={14} strokeWidth={2}/>형식 확인</span>) : <span className="doc-badge none">읽지 못함</span>}</span></div>
          <div className="doc-value"><input id={`${inputId}-mrn`} value={values.mrn ?? ''} spellCheck={false} placeholder="예: 26ABCD1234I" aria-invalid={!mrnValid}
            onChange={e => setValues(v => ({...v, mrn: e.target.value}))}/><Pencil size={16} strokeWidth={1.75} aria-hidden="true"/></div>
        </div>
      </div>
      {!blValid && <p className="field-error">B/L 번호를 영문·숫자 8~20자로 고쳐 주세요.</p>}
      </section>

      {/* inline 모드는 조건·연락처를 접어 둔다(선택 입력이라 카드를 짧게). 기본 모드는 그대로 펼쳐 보인다 */}
      {inline ? <details className="doc-cond-fold"><summary>B/L 조건과 화물 인도 연락처 (선택)</summary>{conditions}</details> : conditions}

      {/* 사용법 문장은 지우고, 판단에 쓰이는 주의·저장 안내만 한 번 접어 둔다 (C-275) */}
      <details className="doc-notes">
        <summary><strong>자세히 보기</strong><span>사진을 읽은 방식과 저장 안내</span></summary>
        <p>사진에서 글자 {result.ocr.lines}줄을 읽었어요.</p>
        <p>서류에 적힌 지시문은 따르지 않고 글자로만 읽어요. 칸이 서로 바뀌어 읽혔을 수 있으니 서류와 한 번 맞춰 보세요.</p>
        <p>{isLive ? '로그인한 상태면 위에서 고른 B/L 조건과 연락처를 "내 기억"에 저장해 다음 조회 때 짚어 드려요. "모름"으로 둔 칸은 저장하지 않아요.' : '체험 모드에서는 B/L 조건과 연락처를 저장하지 않아요.'}</p>
      </details>

      <div className="doc-actions">
        {/* 10-08 정운 53번: inline에서는 칩의 X가 "다른 사진" 역할을 한다. 아래 입력창에 쓴 설명도 같이 보낸다는 것을 버튼 옆에 알린다 */}
        {inline ? <span className="doc-actions-hint">아래 입력창에 설명을 적으면 함께 보내요</span>
          : <button type="button" className="button secondary" onClick={() => { setResult(null); setError(''); }}><RotateCcw size={16}/>다른 사진</button>}
        <button type="button" className="button primary" onClick={apply} disabled={!canApply || disabled}>{inline ? '확인한 값으로 조회' : '확인한 값으로 채우기'}</button>
      </div>
    </div>}
  </section>;
}
