'use client';
/** 고객 한 명에 대한 운영자 동작 패널 (docs/specs/operator-admin.md 추가 절). 고객 관리 표의 행 아래에 펼친다.
 *
 * - 마스킹 해제: 사유서(10~500자)를 써야 서버가 기록한 뒤 원문을 준다. 화면은 60초 뒤 다시 가린다
 * - 수정: 이름·휴대전화·주소. 검사는 본인 입력과 같은 규칙. 이메일은 구글 계정이라 못 바꾼다
 * - 강제 탈퇴: 고객 이메일 앞부분을 다시 입력해야 버튼이 켜진다. 운영자 계정은 서버가 409로 막는다
 * 모든 동작은 서버 이력(admin_actions)에 남는다. 화면이 따로 남기지 않는다.
 */
import {useEffect, useRef, useState, type FormEvent} from 'react';
import {Eye, EyeOff, LoaderCircle, Pause, PencilLine, Play, Timer, UserRoundX} from 'lucide-react';
import {deleteCustomer, resumeCustomer, suspendCustomer, unmaskCustomer, updateCustomer} from '@/lib/api';
import type {CustomerItem, UnmaskResponse} from '@/lib/types';

const REVEAL_SECONDS = 60;  // 원문을 보여 두는 시간. 자리를 비워도 화면에 남아 있지 않게

export type CustomerMode = 'unmask' | 'edit' | 'delete' | 'suspend';

export function CustomerActions({customer, mode, onDone, onClose, onLogged}: {
  customer: CustomerItem; mode: CustomerMode; onDone: (msg: string) => void; onClose: () => void;
  onLogged?: () => void;  // 원문 열람처럼 패널을 연 채로 이력이 남는 동작 뒤에 부른다 (작업 이력에 바로 안 올라옴)
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reason, setReason] = useState('');
  const [raw, setRaw] = useState<UnmaskResponse | null>(null);
  const [left, setLeft] = useState(REVEAL_SECONDS);
  const [form, setForm] = useState({name: '', phone: '', address: ''});
  const [confirmText, setConfirmText] = useState('');
  const root = useRef<HTMLDivElement>(null);
  // 표 아래에 열리므로 화면 밖이면 보이는 곳까지 내려 준다
  useEffect(() => { root.current?.scrollIntoView?.({block: 'nearest', behavior: 'smooth'}); }, []);

  // 원문은 정해진 시간만 보여 주고 지운다
  useEffect(() => {
    if (!raw) return;
    if (left <= 0) { setRaw(null); onClose(); return; }
    const t = setTimeout(() => setLeft(s => s - 1), 1000);
    return () => clearTimeout(t);
  }, [raw, left, onClose]);

  async function run(fn: () => Promise<void>) {
    setBusy(true); setError('');
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : '처리하지 못했어요.'); }
    finally { setBusy(false); }
  }

  function submitUnmask(e: FormEvent) {
    e.preventDefault();
    if (reason.trim().length < 10) { setError('사유를 10자 이상 적어 주세요.'); return; }
    void run(async () => { setRaw(await unmaskCustomer(customer.user_id, reason.trim())); setLeft(REVEAL_SECONDS); onLogged?.(); });
  }

  // 수정은 원문을 미리 채우지 않는다. 원문을 보려면 마스킹 해제(사유서)를 거쳐야 한다
  function submitEdit(e: FormEvent) {
    e.preventDefault();
    void run(async () => { await updateCustomer(customer.user_id, form); onDone('고객 정보를 수정했어요.'); });
  }

  const prefix = (customer.email_masked ?? '').split('*')[0];
  const deleteReady = !!prefix && confirmText.trim() === prefix;

  const dest = customer.name_masked ? ` · ${customer.name_masked}` : '';

  // 시안 4-6: 표 아래 카드. 마스킹 해제·수정은 좌우 두 장, 탈퇴 확인은 한 줄 바
  return <div ref={root} className="customer-actions adm-detail" role="region" aria-label="고객 작업">
    {mode === 'unmask' && (raw
      ? <div className="adm-dcard unmask-result adm-unmask">
          <div className="adm-dcard-head"><h3>원문 열람{dest}</h3>
            {/* 남은 시간은 읽어야 하는 정보라 작은 회색이 아니라 굵은 칩으로 */}
            <span className="adm-timer"><Timer size={16}/>{left}초 뒤에 다시 가려져요</span></div>
          <dl>{([['이메일', raw.email], ['이름', raw.name], ['휴대전화', raw.phone], ['주소', raw.address], ['사유', reason.trim()]] as const).map(([k, v]) =>
            <div key={k}><dt>{k}</dt><dd>{v || '없음'}</dd></div>)}</dl>
          <div className="adm-dcard-foot"><span className="adm-note">이 열람은 사유와 함께 작업 이력에 남았어요.</span>
            <button type="button" className="button secondary" onClick={() => { setRaw(null); onClose(); }}><EyeOff size={16}/>지금 가리기</button></div>
        </div>
      : <form onSubmit={submitUnmask} className="adm-dcard unmask-form adm-form">
          <div className="adm-dcard-head"><h3>마스킹 해제 사유{dest}</h3></div>
          <label htmlFor={`reason-${customer.user_id}`} className="adm-hint-inline">10~500자, 작업 이력에 그대로 남아요</label>
          <textarea id={`reason-${customer.user_id}`} value={reason} onChange={e => setReason(e.target.value)} maxLength={500} rows={3}
            placeholder="예: 고객이 전화로 배송지 확인을 요청해 본인 확인이 필요함" disabled={busy}/>
          <div className="row-actions"><span className="adm-count">{reason.trim().length}/500</span>
            <button type="button" className="button secondary" onClick={onClose} disabled={busy}>취소</button>
            <button className="button primary" disabled={busy || reason.trim().length < 10}>{busy ? <LoaderCircle size={16} className="spin"/> : <Eye size={16}/>}사유 남기고 해제</button></div>
        </form>)}

    {mode === 'edit' && <form onSubmit={submitEdit} className="adm-dcard edit-form adm-form">
      <div className="adm-dcard-head"><h3>고객 정보 수정{dest}</h3></div>
      <div className="edit-grid">
        <div className="form-field"><label htmlFor={`en-${customer.user_id}`}>이름</label><input id={`en-${customer.user_id}`} value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))} placeholder={customer.name_masked ?? ''} disabled={busy}/></div>
        <div className="form-field"><label htmlFor={`ep-${customer.user_id}`}>휴대전화</label><input id={`ep-${customer.user_id}`} value={form.phone} onChange={e => setForm(f => ({...f, phone: e.target.value}))} placeholder={customer.phone_masked ?? '010-1234-5678'} inputMode="numeric" disabled={busy}/></div>
        <div className="form-field"><label htmlFor={`ea-${customer.user_id}`}>주소</label><input id={`ea-${customer.user_id}`} value={form.address} onChange={e => setForm(f => ({...f, address: e.target.value}))} placeholder={customer.address_masked ?? ''} disabled={busy}/></div>
      </div>
      <div className="adm-dcard-foot"><span className="adm-note">새 값을 입력해 주세요. 지금 값은 가려져 있어요(원문은 마스킹 해제로만 볼 수 있어요). 세 칸 모두 필요해요.</span>
        <div className="row-actions"><button type="button" className="button secondary" onClick={onClose} disabled={busy}>취소</button>
          <button className="button primary" disabled={busy || !form.name.trim() || !form.phone.trim() || !form.address.trim()}>{busy ? <LoaderCircle size={16} className="spin"/> : <PencilLine size={16}/>}수정 저장</button></div></div>
    </form>}

    {mode === 'delete' && <div className="adm-dcard adm-delete delete-box adm-form">
      <div className="adm-delete-row">
        <h3>강제 탈퇴 확인{dest}</h3>
        <div className="form-field"><label htmlFor={`del-${customer.user_id}`}>이메일 앞부분 <strong className="mono">{prefix || '(없음)'}</strong> 을 입력해 주세요</label>
          <input id={`del-${customer.user_id}`} value={confirmText} onChange={e => setConfirmText(e.target.value)} autoComplete="off" disabled={busy}/></div>
        <div className="row-actions"><button type="button" className="button secondary" onClick={onClose} disabled={busy}>취소</button>
          <button type="button" className="button danger" disabled={busy || !deleteReady}
            onClick={() => void run(async () => { const r = await deleteCustomer(customer.user_id); onDone(`강제 탈퇴했어요. 조회 이력 ${r.deleted_records}건도 함께 지웠어요.`); })}>
            {busy ? <LoaderCircle size={16} className="spin"/> : <UserRoundX size={16}/>}강제 탈퇴</button></div>
      </div>
      <p className="adm-note">조회 이력, 회원 정보, 계정을 차례로 지워요. 되돌릴 수 없어요.</p>
    </div>}

    {mode === 'suspend' && (customer.is_suspended
      ? <div className="adm-dcard adm-form"><div className="adm-dcard-head"><h3>정지 해제{dest}</h3></div><p className="adm-note">이 고객은 다시 로그인하고 조회할 수 있게 돼요.</p>
          <div className="row-actions"><button type="button" className="button secondary" onClick={onClose} disabled={busy}>취소</button>
            <button type="button" className="button primary" disabled={busy}
              onClick={() => void run(async () => { await resumeCustomer(customer.user_id); onDone('정지를 해제했어요.'); })}>
              {busy ? <LoaderCircle size={16} className="spin"/> : <Play size={16}/>}정지 해제</button></div></div>
      : <form className="adm-dcard unmask-form adm-form" onSubmit={e => { e.preventDefault(); if (reason.trim().length < 10) { setError('사유를 10자 이상 적어 주세요.'); return; }
          void run(async () => { await suspendCustomer(customer.user_id, reason.trim()); onDone('계정을 일시 정지했어요. 이 고객은 지금부터 로그인·조회가 막혀요.'); }); }}>
          <div className="adm-dcard-head"><h3>일시 정지 사유{dest}</h3></div>
          <label htmlFor={`susp-${customer.user_id}`} className="adm-hint-inline">10~500자, 작업 이력에 남아요. 해제할 때까지 로그인·조회가 막혀요</label>
          <textarea id={`susp-${customer.user_id}`} value={reason} onChange={e => setReason(e.target.value)} maxLength={500} rows={3}
            placeholder="예: 이용약관 위반 신고가 접수되어 확인 기간 동안 정지" disabled={busy}/>
          <div className="row-actions"><span className="adm-count">{reason.trim().length}/500</span>
            <button type="button" className="button secondary" onClick={onClose} disabled={busy}>취소</button>
            <button className="button danger-outline secondary" disabled={busy || reason.trim().length < 10}>{busy ? <LoaderCircle size={16} className="spin"/> : <Pause size={16}/>}일시 정지</button></div>
        </form>)}

    {error && <p role="alert" className="request-error">{error}</p>}
  </div>;
}
