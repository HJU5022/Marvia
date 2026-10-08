'use client';
/** 조회 입력 폼 (SDD 5.13 TopBar, 계약 C2). 백엔드와 같은 B/L 정규화·검사를 먼저 해서 400을 줄인다.
 * 판매 예정일은 선택이다. 요청에 status나 fixture ID 같은 칸을 더하지 않는다.
 */
import {useEffect, useState, type FormEvent} from 'react';
import {ArrowRight, Camera, Check, ChevronDown, LoaderCircle, Search, X} from 'lucide-react';
import {useApp} from './AppProvider';
import {DocumentPanel, type DocumentValues} from './DocumentPanel';
import {isLive, liveExamples, selectFixture} from '@/lib/api';
import type {AgentRequest} from '@/lib/types';
import {maskBl} from '@/lib/format';

export function TopBar() {
  const {request, lookup, loading, data, error, docHints, setDocHints} = useApp();
  const [bl, setBl] = useState(request.bl_no);
  const [type, setType] = useState(request.bl_type);
  const [date, setDate] = useState(request.sale_due_date ?? '');
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [choice, setChoice] = useState('');
  const [docOpen, setDocOpen] = useState(false);

  useEffect(() => { setBl(request.bl_no); setType(request.bl_type); setDate(request.sale_due_date ?? ''); }, [request]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const no = bl.replace(/\s/g, '').toUpperCase();
    const next: Record<string, string> = {};
    // backend/app/schemas/agent.py _BL_PATTERN과 같은 규칙
    if (!/^[A-Z0-9]{8,20}$/.test(no)) next.bl = '영문·숫자 8~20자로 입력해 주세요.';
    if (date && (!/^\d{4}-\d{2}-\d{2}$/.test(date) || Number.isNaN(Date.parse(date)))) next.date = '날짜 형식을 확인해 주세요.';
    setErrors(next);
    if (Object.keys(next).length) return;
    setBl(no); selectFixture(null); setChoice('');
    // 서류에서 확인한 출항일은 그 서류의 B/L을 조회할 때만 싣는다. 서버가 화물 표 출항 칸에 적는다
    const departed_on = docHints?.departed_on && docHints.bl_no === no ? docHints.departed_on : null;
    void lookup({bl_no: no, bl_type: type, sale_due_date: date || null, session_id: request.session_id, departed_on});
  }

  /** 데모 모드: 저장된 예시를 바로 재생한다. */
  function chooseDemo(id: string) {
    const c = data.demo.choices.find(c => c.id === id);
    if (!c) return;
    setErrors({}); setChoice(id); selectFixture(id);
    void lookup(c.request as AgentRequest);
  }

  /** 실제 모드: 백엔드 데모 B/L을 폼에 채우기만 한다. 판매 예정일은 예시에 sale_in_days가 있으면 "오늘(한국) + N일"로 채우고, 없으면 비운다. */
  function chooseLive(id: string) {
    const c = liveExamples.find(c => c.id === id);
    if (!c) return;
    // 한국 날짜 기준: UTC 시각에 9시간을 더해 날짜만 자른다 (브라우저 시간대와 상관없이 서버 데모의 "오늘"과 같게)
    const sale = c.sale_in_days != null ? new Date(Date.now() + 9 * 3600_000 + c.sale_in_days * 86_400_000).toISOString().slice(0, 10) : '';
    setErrors({}); setBl(c.bl_no); setType(c.bl_type); setDate(sale);
  }

  /** 서류 사진에서 확인한 값: B/L은 폼에, 항차·입항 예정일은 되묻기 화면용으로 둔다. 조회는 사용자가 누른다. */
  function applyDocument(v: DocumentValues) {
    setBl(v.bl_no); setErrors({}); setDocOpen(false);
    setDocHints(v.voyage_no || v.forwarder_eta || v.departed_on ? {voyage_no: v.voyage_no, forwarder_eta: v.forwarder_eta, bl_no: v.bl_no, departed_on: v.departed_on} : null);
  }

  return <section className="query-section" aria-label="화물 조회">
    <form className="query-form" onSubmit={submit} noValidate>
      <div className="form-field bl-field">
        <label htmlFor="bl">B/L 번호</label>
        <div className="input-icon"><Search size={16}/><input id="bl" value={bl} onChange={e => setBl(e.target.value)} autoComplete="off" spellCheck={false} aria-invalid={!!errors.bl} aria-describedby={errors.bl ? 'bl-error' : undefined} disabled={loading}/></div>
        {errors.bl && <span id="bl-error" className="field-error">{errors.bl}</span>}
      </div>
      <div className="form-field">
        <label htmlFor="bl-type">구분</label>
        <select id="bl-type" value={type} onChange={e => setType(e.target.value as AgentRequest['bl_type'])} disabled={loading}><option value="MASTER">Master B/L</option><option value="HOUSE">House B/L</option></select>
      </div>
      <div className="form-field">
        <label htmlFor="sale-date">판매 예정일 <small>(선택)</small></label>
        <input id="sale-date" type="date" value={date} onChange={e => setDate(e.target.value)} aria-invalid={!!errors.date} aria-describedby={errors.date ? 'date-error' : undefined} disabled={loading}/>
        {errors.date && <span id="date-error" className="field-error">{errors.date}</span>}
      </div>
      <button type="submit" className="button primary query-button" disabled={loading}>{loading ? <LoaderCircle size={17} className="spin"/> : <Search size={17}/>}<span>{loading ? '조회 중' : '화물 조회'}</span>{!loading && <ArrowRight size={16}/>}</button>
    </form>
    <div className="query-foot">
      <div className="query-foot-actions">
      <button type="button" className="doc-trigger" onClick={() => setDocOpen(o => !o)} aria-expanded={docOpen} disabled={loading}><Camera size={13}/>서류 사진으로 채우기</button>
      <label className="example-select">예시 화물 {isLive
        ? <select aria-label="예시 화물" value="" disabled={loading} onChange={e => chooseLive(e.target.value)}><option value="">선택하기</option>{liveExamples.map(c => <option value={c.id} key={c.id}>{c.label} · {c.bl_no}</option>)}</select>
        : <select aria-label="예시 화물" value="" disabled={loading} onChange={e => chooseDemo(e.target.value)}><option value="">선택하기</option>{data.demo.choices.slice(0, 3).map(c => <option value={c.id} key={c.id}>{c.label} · {maskBl(c.request.bl_no)}</option>)}</select>}
        <ChevronDown size={12}/></label>
      </div>
    </div>
    {docOpen && <DocumentPanel onApply={applyDocument} onClose={() => setDocOpen(false)} disabled={loading}/>}
    {docHints && !docOpen && <p className="doc-hint"><Camera size={13}/>서류에서 확인한 값
      {docHints.voyage_no && <> · 항차 <strong>{docHints.voyage_no}</strong></>}
      {docHints.forwarder_eta && <> · 입항 예정 <strong>{docHints.forwarder_eta}</strong></>}
      {docHints.departed_on && <> · 출항 <strong>{docHints.departed_on}</strong></>}
      <button type="button" onClick={() => setDocHints(null)} aria-label="서류 값 지우기"><X size={14}/></button></p>}
    {!isLive && process.env.NODE_ENV === 'development' && <div className="dev-switch"><span className="mono">DEV</span><label htmlFor="fixture">상태 미리보기</label><select id="fixture" value={choice} onChange={e => chooseDemo(e.target.value)} disabled={loading}><option value="">B/L에 맞는 예시</option>{data.demo.choices.map(c => <option key={c.id} value={c.id}>{c.id} · {c.label}</option>)}</select></div>}
    {/* 진행 단계는 화면 타이머다. 백엔드는 진행 이벤트를 보내지 않는다 (REST 응답 하나) */}
    {/* 타이머 3단계 표시는 지웠다. 서버의 실제 단계 소식으로 바꿨다 (docs/specs/chat-progress.md). 이 폼은 지금 쓰이지 않는다 */}
    {error && <p role="alert" className="request-error">{error} <span>아래에 결과가 있다면 이전 조회의 결과예요.</span></p>}
  </section>;
}
