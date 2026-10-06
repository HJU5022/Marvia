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
 */
import {useId, useRef, useState, type ChangeEvent, type DragEvent} from 'react';
import {Camera, Check, FileImage, LoaderCircle, RotateCcw, TriangleAlert, X} from 'lucide-react';
import {isLive, readDocument, saveDocumentFacts} from '@/lib/api';
import type {ContactRole, DocumentCheck, DocumentConditionKey, DocumentFactsRequest, DocumentResponse, FreightTerm, Incoterm, OriginalBl} from '@/lib/types';

const FIELD_LABELS: [keyof DocumentResponse['fields'], string, string][] = [
  ['bl_no', 'B/L 번호', '조회에 사용'],
  ['voyage', '항차', '배 확인이 필요할 때 사용'],
  ['eta', '입항 예정일', '배 확인이 필요할 때 사용'],
  ['etd', '출항일', '내 화물 현황 표에 기록 · 판정에는 안 씀'],
  ['vessel', '선명', '확인용'],
  ['pol', '선적항', '확인용'],
  ['pod', '양하항', '확인용'],
  ['item', '품명', '확인용 · 저장 안 함'],
];
/** 검사 이름은 services/doc_ocr.check_fields와 같다. */
const CHECK_LABELS: Record<DocumentCheck, string> = {
  missing: '읽지 못함',
  not_in_text: '서류에서 찾지 못한 값',
  format: '형식 확인',
  ambiguous: '두 군데서 다른 값',
};
const EDITABLE = new Set(['bl_no', 'voyage', 'eta', 'etd']);
/** B/L 조건 고르기 칸. 값은 backend/app/schemas/memory.py, 마이그레이션 015 CHECK와 같다. 빈 값은 "모름" */
const CONDITION_CHOICES: [DocumentConditionKey, string, [string, string][]][] = [
  ['original_bl', '원본 B/L', [['required', '원본 필요'], ['surrendered', '서렌더(원본 불필요)']]],
  ['to_order_bank', '수하인', [['true', '은행 지시식(TO ORDER OF 은행)'], ['false', '은행 지시식 아님']]],
  ['freight_term', '운임', [['prepaid', '선불(PREPAID)'], ['collect', '착불(COLLECT)']]],
  ['incoterm', '거래 조건', [['CIF', 'CIF'], ['FOB', 'FOB'], ['CFR', 'CFR']]],
  ['contact_role', '연락처 역할', [['포워더', '포워더'], ['관세사', '관세사'], ['수출자', '수출자'], ['판매처', '판매처']]],
];
/** 연락처 두 칸의 이름. 배너에서 "확인이 필요한 칸"을 이름으로 말하려고 같이 둔다 */
const CONTACT_LABELS: [DocumentConditionKey, string][] = [['contact_company', '연락처 회사'], ['contact_phone', '회사 전화']];
const CONDITION_KEYS: DocumentConditionKey[] = ['original_bl', 'to_order_bank', 'freight_term', 'incoterm', 'contact_company', 'contact_role', 'contact_phone'];

/** 칸 위 오른쪽에 붙는 검사 결과 배지. 걸린 검사는 주의색, 통과·서류에 없음은 중립 회색 (신호등 색은 판정 등급 전용) */
function CheckBadges({checks, okWhen = true, emptyText}: {checks: DocumentCheck[]; okWhen?: boolean; emptyText?: string}) {
  if (checks.length) return <>{checks.map(c => <span key={c} className="doc-badge warn"><TriangleAlert size={12}/>{CHECK_LABELS[c]}</span>)}</>;
  if (!okWhen) return <span className="doc-badge none">{emptyText ?? '서류에 없음'}</span>;
  return <span className="doc-badge ok"><Check size={12}/>통과</span>;
}

export interface DocumentValues { bl_no: string; voyage_no: string | null; forwarder_eta: string | null; mrn: string | null; departed_on: string | null }

/** heading=false: 드로어(Drawer)가 제목과 닫기 버튼을 그릴 때. 제목·닫기가 두 번 보이지 않게 한다 (ChatBar) */
export function DocumentPanel({onApply, onClose, disabled, heading = true}: {onApply: (v: DocumentValues) => void; onClose: () => void; disabled: boolean; heading?: boolean}) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [fileName, setFileName] = useState('');
  const [result, setResult] = useState<DocumentResponse | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [dragging, setDragging] = useState(false);

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
      setError(e instanceof Error ? e.message : '사진을 읽지 못했습니다. 다시 시도해 주세요.');
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';  // 같은 파일을 다시 골라도 change가 나게
    }
  }

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

  function apply() {
    if (!blValid || !etaValid || !etdValid) return;
    rememberFacts();
    // MRN은 세관에 아직 없는 화물을 해수부 입항 신고로 찾을 때 쓴다 (docs/specs/mrn-fallback.md)
    onApply({bl_no: bl, voyage_no: values.voyage?.trim() || null, forwarder_eta: eta || null, mrn: mrnValid ? mrn || null : null, departed_on: etd || null});
  }

  // 배너에 "어느 칸을 봐야 하는지" 이름으로 보이려고, 검사에 걸린 칸의 이름을 모은다 (순서는 화면 순서)
  const flaggedNames = result ? [
    ...FIELD_LABELS.map(([k, l]) => [k, l] as const),
    ...CONDITION_CHOICES.map(([k, l]) => [k, l] as const),
    ...CONTACT_LABELS.map(([k, l]) => [k, l] as const),
  ].filter(([k]) => (result.fields[k]?.checks.length ?? 0) > 0).map(([, l]) => l) : [];
  const conditionFlagged = result ? [...CONDITION_CHOICES.map(c => c[0]), ...CONTACT_LABELS.map(c => c[0])].some(k => (result.fields[k]?.checks.length ?? 0) > 0) : false;
  const mainFields = FIELD_LABELS.filter(([k]) => k !== 'item');  // 품명은 맨 뒤로 보내 읽기만 하는 칸을 모은다

  return <section className={`document-panel ${heading ? '' : 'in-drawer'}`} aria-label="서류 사진으로 채우기">
    {heading && <div className="document-head">
      <div><span className="eyebrow">ARRIVAL NOTICE · B/L PHOTO</span><h2>서류 사진으로 채우기</h2></div>
      <button type="button" className="icon-button" onClick={onClose} aria-label="서류 사진 닫기"><X size={18}/></button>
    </div>}

    {!result && <label htmlFor={inputId} className={`dropzone ${dragging ? 'dragging' : ''} ${busy ? 'busy' : ''} ${disabled ? 'disabled' : ''}`} aria-disabled={disabled || undefined}
      onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
      {busy ? <LoaderCircle size={30} className="spin"/> : <Camera size={30} strokeWidth={1.3}/>}
      <strong>{busy ? '사진에서 글자를 읽는 중' : '사진을 끌어 놓거나 눌러서 고르세요'}</strong>
      <span>{busy ? fileName : 'JPG·PNG, 10MB 이하 · 사진은 저장하지 않습니다'}</span>
      <input ref={inputRef} id={inputId} type="file" accept="image/*" className="sr-only" disabled={busy || disabled}
        onChange={(e: ChangeEvent<HTMLInputElement>) => void upload(e.target.files?.[0])}/>
    </label>}

    {error && <p role="alert" className="request-error">{error}</p>}

    {result && <div className="document-result">
      <div className={`document-status ${result.needs_review ? 'review' : 'clear'}`}>
        {result.needs_review ? <TriangleAlert size={20}/> : <Check size={20}/>}
        <div><strong>{result.needs_review ? '확인이 필요한 칸이 있어요.' : '모든 칸이 검사를 통과했어요.'}</strong>
          {result.needs_review && flaggedNames.length > 0 && <span className="doc-flagged-names">{flaggedNames.join(' · ')}</span>}
          <span>{result.status === 'partial' ? 'B/L 번호만 읽었습니다. 나머지 칸은 직접 확인해 주세요. ' : ''}
            <FileImage size={14}/> {fileName}</span></div>
        {!isLive && <span className="subtle-badge">가공 예시</span>}
      </div>
      {/* 10-06: AI 단계가 실패하면 빈 칸이 서류 탓처럼 보인다. 실패했다고 알리고 사진을 다시 올리게 한다 ("다른 사진" 버튼) */}
      {result.llm_error && <p role="alert" className="request-error">AI가 서류 글자를 정리하지 못했어요. 다시 시도해 주세요.</p>}

      <h3 className="doc-section-title">서류에서 읽은 값</h3>
      <div className="doc-fields">
        {[...mainFields, ...FIELD_LABELS.filter(([k]) => k === 'item')].map(([key, label, use]) => {
          const f = result.fields[key] ?? {value: null, checks: []};  // etd는 옛 서버 응답에 없을 수 있다
          const id = `${inputId}-${key}`;
          return <div key={key} className={`doc-field ${f.checks.length ? 'flagged' : ''}`}>
            <div className="doc-field-top"><label htmlFor={id}>{label}</label>
              <span className="doc-badges">{key === 'etd' && !f.value && !f.checks.length ? <CheckBadges checks={[]} okWhen={false}/> : <CheckBadges checks={f.checks}/>}</span></div>
            {EDITABLE.has(key)
              ? <input id={id} value={values[key] ?? ''} type={key === 'eta' || key === 'etd' ? 'date' : 'text'} spellCheck={false}
                  onChange={e => setValues(v => ({...v, [key]: e.target.value}))} aria-invalid={f.checks.length > 0 || (key === 'bl_no' && !blValid)}/>
              : <output id={id}>{f.value ?? '읽지 못함'}</output>}
            <small>{use}</small>
          </div>;
        })}
        <div className={`doc-field ${values.mrn && !mrnValid ? 'flagged' : ''}`}>
          <div className="doc-field-top"><label htmlFor={`${inputId}-mrn`}>화물관리번호(MRN)</label>
            <span className="doc-badges">{values.mrn ? (mrnValid ? <span className="doc-badge ok"><Check size={12}/>형식 맞음</span> : <span className="doc-badge warn"><TriangleAlert size={12}/>형식 확인</span>) : <span className="doc-badge none">읽지 못함</span>}</span></div>
          <input id={`${inputId}-mrn`} value={values.mrn ?? ''} spellCheck={false} placeholder="예: 26ABCD1234I" aria-invalid={!mrnValid}
            onChange={e => setValues(v => ({...v, mrn: e.target.value}))}/>
          <small>세관 조회가 안 될 때 해수부 입항 신고로 배 찾기</small>
        </div>
      </div>
      {!blValid && <p className="field-error">B/L 번호를 영문·숫자 8~20자로 고쳐 주세요.</p>}

      {/* B/L 조건·연락처는 조회에 안 쓰이는 보조 입력이라 접어 둔다. 검사에 걸린 칸이 있으면 놓치지 않게 펼쳐 둔다 */}
      <details className="doc-more" open={conditionFlagged || undefined}>
        <summary><span>B/L 조건 · 화물 인도 연락처</span><small>기억에만 사용 · 판정에는 안 씀</small></summary>
        <div className="doc-fields light">
          {CONDITION_CHOICES.map(([key, label, choices]) => {
            const f = result.fields[key] ?? {value: null, checks: []};
            const id = `${inputId}-${key}`;
            return <div key={key} className={`doc-field ${f.checks.length ? 'flagged' : ''}`}>
              <div className="doc-field-top"><label htmlFor={id}>{label}</label>
                <span className="doc-badges"><CheckBadges checks={f.checks} okWhen={!!f.value}/></span></div>
              <select id={id} value={values[key] ?? ''} onChange={e => setValues(v => ({...v, [key]: e.target.value}))} aria-invalid={f.checks.length > 0}>
                <option value="">모름</option>
                {choices.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
              </select>
              {f.checks.length > 0 && f.value && <small>읽은 값: {choices.find(c => c[0] === f.value)?.[1] ?? f.value}</small>}
            </div>;
          })}
          {CONTACT_LABELS.map(([key, label]) => {
            const f = result.fields[key] ?? {value: null, checks: []};
            const id = `${inputId}-${key}`;
            return <div key={key} className={`doc-field ${f.checks.length ? 'flagged' : ''}`}>
              <div className="doc-field-top"><label htmlFor={id}>{label}</label>
                <span className="doc-badges"><CheckBadges checks={f.checks} okWhen={!!f.value}/></span></div>
              <input id={id} value={values[key] ?? ''} spellCheck={false} maxLength={key === 'contact_company' ? 40 : 20}
                onChange={e => setValues(v => ({...v, [key]: e.target.value}))} aria-invalid={f.checks.length > 0}/>
              <small>{f.checks.length && f.value ? `읽은 값: ${f.value}` : key === 'contact_company' ? '회사 이름만 · 개인 이름 안 받음' : '숫자와 하이픈 · 개인 휴대폰 안 받음'}</small>
            </div>;
          })}
        </div>
      </details>

      <div className="doc-actions">
        <button type="button" className="button secondary" onClick={() => { setResult(null); setError(''); }}><RotateCcw size={16}/>다른 사진</button>
        <button type="button" className="button primary" onClick={apply} disabled={!blValid || !etaValid || !etdValid || !mrnValid || disabled}><Check size={16}/>확인한 값으로 채우기</button>
      </div>
      {/* 사용법 문장은 지우고, 판단에 쓰이는 주의·저장 안내만 한 번 접어 둔다 (C-275) */}
      <details className="doc-notes">
        <summary>자세히 보기</summary>
        <p>서류의 지시문은 따르지 않고 글자로만 읽습니다. 칸이 서로 바뀌어 읽혔을 수 있으니 서류와 한 번 맞춰 보세요.</p>
        <p>{isLive ? '로그인한 상태면 위에서 고른 B/L 조건과 연락처를 "내 기억"에 저장해 다음 조회 때 짚어 드립니다. "모름"으로 둔 칸은 저장하지 않습니다.' : '데모 모드에서는 B/L 조건과 연락처를 저장하지 않습니다.'}</p>
      </details>
    </div>}
  </section>;
}
