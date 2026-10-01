'use client';
/** 고객 한 명에 대한 운영자 동작 패널 (docs/specs/operator-admin.md 추가 절). 고객 관리 표의 행 아래에 펼친다.
 *
 * - 마스킹 해제: 사유서(10~500자)를 써야 서버가 기록한 뒤 원문을 준다. 화면은 60초 뒤 다시 가린다
 * - 수정: 이름·휴대전화·주소. 검사는 본인 입력과 같은 규칙. 이메일은 구글 계정이라 못 바꾼다
 * - 강제 탈퇴: 고객 이메일 앞부분을 다시 입력해야 버튼이 켜진다. 운영자 계정은 서버가 409로 막는다
 * 모든 동작은 서버 이력(admin_actions)에 남는다. 화면이 따로 남기지 않는다.
 */
import {useEffect, useState, type FormEvent} from 'react';
import {Eye, EyeOff, LoaderCircle, PencilLine, UserRoundX} from 'lucide-react';
import {deleteCustomer, unmaskCustomer, updateCustomer} from '@/lib/api';
import type {CustomerItem, UnmaskResponse} from '@/lib/types';

const REVEAL_SECONDS = 60;  // 원문을 보여 두는 시간. 자리를 비워도 화면에 남아 있지 않게

export type CustomerMode = 'unmask' | 'edit' | 'delete';

export function CustomerActions({customer, mode, onDone, onClose}: {
  customer: CustomerItem; mode: CustomerMode; onDone: (msg: string) => void; onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reason, setReason] = useState('');
  const [raw, setRaw] = useState<UnmaskResponse | null>(null);
  const [left, setLeft] = useState(REVEAL_SECONDS);
  const [form, setForm] = useState({name: '', phone: '', address: ''});
  const [confirmText, setConfirmText] = useState('');

  // 원문은 정해진 시간만 보여 주고 지운다
  useEffect(() => {
    if (!raw) return;
    if (left <= 0) { setRaw(null); onClose(); return; }
    const t = setTimeout(() => setLeft(s => s - 1), 1000);
    return () => clearTimeout(t);
  }, [raw, left, onClose]);

  async function run(fn: () => Promise<void>) {
    setBusy(true); setError('');
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : '처리하지 못했습니다.'); }
    finally { setBusy(false); }
  }

  function submitUnmask(e: FormEvent) {
    e.preventDefault();
    if (reason.trim().length < 10) { setError('사유를 10자 이상 적어 주세요.'); return; }
    void run(async () => { setRaw(await unmaskCustomer(customer.user_id, reason.trim())); setLeft(REVEAL_SECONDS); });
  }

  // 수정은 원문을 미리 채우지 않는다. 원문을 보려면 마스킹 해제(사유서)를 거쳐야 한다
  function submitEdit(e: FormEvent) {
    e.preventDefault();
    void run(async () => { await updateCustomer(customer.user_id, form); onDone('고객 정보를 수정했습니다.'); });
  }

  const prefix = (customer.email_masked ?? '').split('*')[0];
  const deleteReady = !!prefix && confirmText.trim() === prefix;

  return <div className="customer-actions" role="region" aria-label="고객 작업">
    {mode === 'unmask' && (raw
      ? <div className="unmask-result">
          <div className="unmask-head"><strong><Eye size={15}/>원문 보기</strong><span className="mono">{left}초 뒤 다시 가림</span>
            <button type="button" className="button secondary" onClick={() => { setRaw(null); onClose(); }}><EyeOff size={14}/>지금 가리기</button></div>
          <dl>{([['이메일', raw.email], ['이름', raw.name], ['휴대전화', raw.phone], ['주소', raw.address]] as const).map(([k, v]) =>
            <div key={k}><dt>{k}</dt><dd className="mono">{v ?? '없음'}</dd></div>)}</dl>
          <p className="help-text">이 열람은 사유와 함께 작업 이력에 남았습니다.</p>
        </div>
      : <form onSubmit={submitUnmask} className="unmask-form">
          <label htmlFor={`reason-${customer.user_id}`}><strong>마스킹 해제 사유서</strong> <span className="muted">10~500자, 작업 이력에 그대로 남습니다</span></label>
          <textarea id={`reason-${customer.user_id}`} value={reason} onChange={e => setReason(e.target.value)} maxLength={500} rows={3}
            placeholder="예: 고객이 전화로 배송지 확인을 요청해 본인 확인이 필요함" disabled={busy}/>
          <div className="row-actions"><span className="mono muted">{reason.trim().length}/500</span>
            <button type="button" className="button secondary" onClick={onClose} disabled={busy}>취소</button>
            <button className="button primary" disabled={busy || reason.trim().length < 10}>{busy ? <LoaderCircle size={14} className="spin"/> : <Eye size={14}/>}사유 남기고 해제</button></div>
        </form>)}

    {mode === 'edit' && <form onSubmit={submitEdit} className="edit-form">
      <p className="muted">새 값을 입력하세요. 지금 값은 보이지 않습니다(원문은 마스킹 해제로만 봅니다). 세 칸 모두 필요합니다.</p>
      <div className="edit-grid">
        <div className="form-field"><label htmlFor={`en-${customer.user_id}`}>이름</label><input id={`en-${customer.user_id}`} value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))} placeholder={customer.name_masked ?? ''} disabled={busy}/></div>
        <div className="form-field"><label htmlFor={`ep-${customer.user_id}`}>휴대전화</label><input id={`ep-${customer.user_id}`} value={form.phone} onChange={e => setForm(f => ({...f, phone: e.target.value}))} placeholder={customer.phone_masked ?? '010-1234-5678'} inputMode="numeric" disabled={busy}/></div>
        <div className="form-field wide"><label htmlFor={`ea-${customer.user_id}`}>주소</label><input id={`ea-${customer.user_id}`} value={form.address} onChange={e => setForm(f => ({...f, address: e.target.value}))} placeholder={customer.address_masked ?? ''} disabled={busy}/></div>
      </div>
      <div className="row-actions"><button type="button" className="button secondary" onClick={onClose} disabled={busy}>취소</button>
        <button className="button primary" disabled={busy || !form.name.trim() || !form.phone.trim() || !form.address.trim()}>{busy ? <LoaderCircle size={14} className="spin"/> : <PencilLine size={14}/>}수정 저장</button></div>
    </form>}

    {mode === 'delete' && <div className="delete-box">
      <p><strong>강제 탈퇴</strong> 조회 기록, 회원 정보, 계정을 차례로 지웁니다. 되돌릴 수 없습니다.</p>
      <div className="form-field"><label htmlFor={`del-${customer.user_id}`}>확인을 위해 이메일 앞부분 <strong className="mono">{prefix || '(없음)'}</strong> 을 입력하세요</label>
        <input id={`del-${customer.user_id}`} value={confirmText} onChange={e => setConfirmText(e.target.value)} autoComplete="off" disabled={busy}/></div>
      <div className="row-actions"><button type="button" className="button secondary" onClick={onClose} disabled={busy}>취소</button>
        <button type="button" className="button danger" disabled={busy || !deleteReady}
          onClick={() => void run(async () => { const r = await deleteCustomer(customer.user_id); onDone(`강제 탈퇴했습니다. 조회 기록 ${r.deleted_records}건을 함께 지웠습니다.`); })}>
          {busy ? <LoaderCircle size={14} className="spin"/> : <UserRoundX size={14}/>}탈퇴시키기</button></div>
    </div>}

    {error && <p role="alert" className="request-error">{error}</p>}
  </div>;
}
