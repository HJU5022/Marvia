'use client';
/** 서류 사진으로 입력 채우기 (작업 E2 "서류 사진", docs/specs/document-extract.md).
 *
 * 흐름: 사진 올리기 → POST /api/document → 7칸 확인 화면 → 사용자가 고친 값만 폼에 넣는다.
 * 읽은 값으로 바로 조회하지 않는다 (Spec "사용자 확인 화면", SDD 비전 울타리). 검사에 걸린 칸은 "확인 필요"로 드러낸다.
 * B/L은 조회 폼에 바로 넣고, 항차·입항 예정일은 되묻기 화면(CandidatePicker)에 미리 채울 값으로만 둔다.
 * 첫 조회에 섞어 보내면 백엔드가 되묻기 답으로 읽기 때문이다 (schemas/agent.py "선택 칸으로 첫 조회/되묻기 답 구분").
 * 품명·선적항·양하항은 확인용으로만 보여 주고 어디에도 보내거나 저장하지 않는다 (CLAUDE.md 품명 비저장).
 */
import {useId, useRef, useState, type ChangeEvent, type DragEvent} from 'react';
import {Camera, Check, FileImage, LoaderCircle, RotateCcw, TriangleAlert, X} from 'lucide-react';
import {isLive, readDocument} from '@/lib/api';
import type {DocumentCheck, DocumentResponse} from '@/lib/types';

const FIELD_LABELS: [keyof DocumentResponse['fields'], string, string][] = [
  ['bl_no', 'B/L 번호', '조회에 사용'],
  ['voyage', '항차', '배 확인이 필요할 때 사용'],
  ['eta', '입항 예정일', '배 확인이 필요할 때 사용'],
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
  ambiguous: '두 군데서 다른 값이 읽힘',
};
const EDITABLE = new Set(['bl_no', 'voyage', 'eta']);

export interface DocumentValues { bl_no: string; voyage_no: string | null; forwarder_eta: string | null; mrn: string | null }

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
      setValues({...Object.fromEntries(Object.entries(r.fields).map(([k, f]) => [k, f.value ?? ''])), mrn: r.mrn ?? ''});
    } catch (e) {
      setError(e instanceof Error ? e.message : '사진을 읽지 못했습니다. 다시 시도해 주세요.');
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';  // 같은 파일을 다시 골라도 change가 나게
    }
  }

  function onDrop(e: DragEvent) { e.preventDefault(); setDragging(false); void upload(e.dataTransfer.files[0]); }

  const bl = (values.bl_no ?? '').replace(/\s/g, '').toUpperCase();
  const blValid = /^[A-Z0-9]{8,20}$/.test(bl);  // schemas/agent.py _BL_PATTERN
  const eta = values.eta ?? '';
  const etaValid = !eta || /^\d{4}-\d{2}-\d{2}$/.test(eta);
  const mrn = (values.mrn ?? '').replace(/\s/g, '').toUpperCase();
  const mrnValid = !mrn || /^[0-9]{2}[A-Z0-9]{8}[IE]$/.test(mrn);  // schemas/agent.py _MRN_PATTERN

  function apply() {
    if (!blValid || !etaValid) return;
    // MRN은 세관에 아직 없는 화물을 해수부 입항 신고로 찾을 때 쓴다 (docs/specs/mrn-fallback.md)
    onApply({bl_no: bl, voyage_no: values.voyage?.trim() || null, forwarder_eta: eta || null, mrn: mrnValid ? mrn || null : null});
  }

  return <section className={`document-panel ${heading ? '' : 'in-drawer'}`} aria-label="서류 사진으로 채우기">
    {heading && <div className="document-head">
      <div><span className="eyebrow">ARRIVAL NOTICE · B/L PHOTO</span><h2>서류 사진으로 채우기</h2>
        <p>도착 통지서나 B/L 사진에서 조회 값을 읽습니다. 읽은 값은 확인한 뒤에만 사용합니다.</p></div>
      <button type="button" className="icon-button" onClick={onClose} aria-label="서류 사진 닫기"><X size={18}/></button>
    </div>}

    {!result && <label htmlFor={inputId} className={`dropzone ${dragging ? 'dragging' : ''} ${busy ? 'busy' : ''}`}
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
        {result.needs_review ? <TriangleAlert size={18}/> : <Check size={18}/>}
        <div><strong>{result.needs_review ? '확인이 필요한 칸이 있어요.' : '모든 칸이 검사를 통과했어요.'}</strong>
          <span>{result.status === 'partial' ? 'B/L 번호만 읽었습니다. 나머지 칸은 직접 확인해 주세요. ' : ''}
            <FileImage size={12}/> {fileName}</span></div>
        {!isLive && <span className="subtle-badge">가공 예시</span>}
      </div>
      <div className="document-fields">
        {FIELD_LABELS.map(([key, label, use]) => {
          const f = result.fields[key];
          const id = `${inputId}-${key}`;
          return <div key={key} className={`document-field ${f.checks.length ? 'flagged' : ''}`}>
            <label htmlFor={id}>{label}<small>{use}</small></label>
            {EDITABLE.has(key)
              ? <input id={id} value={values[key] ?? ''} type={key === 'eta' ? 'date' : 'text'} spellCheck={false}
                  onChange={e => setValues(v => ({...v, [key]: e.target.value}))} aria-invalid={f.checks.length > 0 || (key === 'bl_no' && !blValid)}/>
              : <output id={id}>{f.value ?? '읽지 못함'}</output>}
            <span className="document-checks">{f.checks.length
              ? f.checks.map(c => <span key={c} className="check-chip">{CHECK_LABELS[c]}</span>)
              : <span className="check-ok"><Check size={12}/>통과</span>}</span>
          </div>;
        })}
      </div>
      <div className="document-field mrn-field"><label htmlFor={`${inputId}-mrn`}>화물관리번호(MRN)<small>세관 조회가 안 될 때 해수부 입항 신고로 배 찾기</small></label>
        <input id={`${inputId}-mrn`} value={values.mrn ?? ''} spellCheck={false} placeholder="예: 26ABCD1234I" aria-invalid={!mrnValid}
          onChange={e => setValues(v => ({...v, mrn: e.target.value}))}/>
        <span className="document-checks">{values.mrn ? (mrnValid ? <span className="check-ok"><Check size={12}/>형식 맞음</span> : <span className="check-chip">형식 확인</span>) : <span className="check-chip">읽지 못함</span>}</span></div>
      {!blValid && <p className="field-error">B/L 번호를 영문·숫자 8~20자로 고쳐 주세요.</p>}
      <div className="button-row">
        <button type="button" className="button primary" onClick={apply} disabled={!blValid || !etaValid || !mrnValid || disabled}><Check size={16}/>확인한 값으로 채우기</button>
        <button type="button" className="button secondary" onClick={() => { setResult(null); setError(''); }}><RotateCcw size={15}/>다른 사진</button>
      </div>
      <p className="help-text">서류의 지시문은 따르지 않고 글자로만 읽습니다. 칸이 서로 바뀌어 읽혔을 수 있으니 서류와 한 번 맞춰 보세요.</p>
    </div>}
  </section>;
}
