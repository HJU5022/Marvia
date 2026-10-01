'use client';
/** 설정 화면의 "계정과 기록" 구역. 내 기록 삭제(DELETE /api/history)와 회원 탈퇴(DELETE /api/account)를 부른다.
 *
 * 둘 다 되돌릴 수 없어서 한 번 더 확인한다. 브라우저 confirm 창 대신 화면 안에서 확인한다(접근성, 목업 톤).
 * 탈퇴는 "탈퇴"를 직접 입력해야 버튼이 켜진다. 실패(503)는 숨기지 않고, 다시 누르면 백엔드가 이어서 끝낸다 (services/account.py).
 * 로그인이 꺼진 환경에는 지울 "내" 기록이 없다. 그 기록은 90일 자동 삭제로 정리된다는 안내만 한다 (routers/history.py).
 */
import {useState} from 'react';
import {LoaderCircle, Trash2, UserRoundX} from 'lucide-react';
import {useApp} from './AppProvider';
import {SectionTitle} from './Shared';
import {deleteMyAccount, deleteMyHistory, isLive} from '@/lib/api';
import {signOut} from '@/lib/auth';

type Step = 'idle' | 'confirm' | 'busy' | 'done';

export function AccountPanel() {
  const {authEnabled, user, reset} = useApp();
  const [historyStep, setHistoryStep] = useState<Step>('idle');
  const [accountStep, setAccountStep] = useState<Step>('idle');
  const [typed, setTyped] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const usable = isLive && authEnabled && !!user;

  async function removeHistory() {
    setHistoryStep('busy'); setError(''); setMessage('');
    try {
      const r = await deleteMyHistory();
      setMessage(`조회 기록 ${r.deleted}건을 지웠습니다.`); setHistoryStep('done'); reset();
    } catch (e) { setError(e instanceof Error ? e.message : '기록을 지우지 못했습니다.'); setHistoryStep('confirm'); }
  }

  async function removeAccount() {
    setAccountStep('busy'); setError(''); setMessage('');
    try {
      const r = await deleteMyAccount();
      setMessage(`조회 기록 ${r.deleted_records}건과 계정을 지웠습니다. 이용해 주셔서 감사합니다.`); setAccountStep('done');
      await signOut(); reset();  // 서버에서 계정이 지워졌으니 브라우저의 로그인 정보도 지운다
    } catch (e) { setError(e instanceof Error ? e.message : '탈퇴를 끝내지 못했습니다.'); setAccountStep('confirm'); }
  }

  return <section className="account-panel" aria-labelledby="account-title">
    <SectionTitle label="계정과 기록" kicker="YOUR DATA, YOUR CALL"/>
    <span id="account-title" className="sr-only">계정과 기록</span>
    {!usable ? <p className="muted account-off">{!isLive
      ? '데모 모드에는 실제 계정과 기록이 없습니다.'
      : !authEnabled
        ? '이 서버는 로그인이 꺼져 있어 기록을 사람별로 나누지 않습니다. 조회 기록은 90일 뒤 자동으로 지워집니다.'
        : '로그인하면 내 기록을 지우거나 탈퇴할 수 있습니다.'}</p>
    : <>
      <p className="account-who">로그인 계정 <strong>{user.email ?? user.name ?? user.id}</strong></p>
      <div className="danger-row">
        <div><h3><Trash2 size={16}/>내 조회 기록 지우기</h3><p>지금까지 조회한 기록을 모두 지웁니다. 계정은 남습니다. 되돌릴 수 없습니다.</p></div>
        {historyStep === 'confirm' || historyStep === 'busy'
          ? <div className="danger-actions"><button type="button" className="button danger" onClick={() => void removeHistory()} disabled={historyStep === 'busy'}>{historyStep === 'busy' ? <LoaderCircle size={15} className="spin"/> : <Trash2 size={15}/>}모두 지우기</button><button type="button" className="button secondary" onClick={() => setHistoryStep('idle')} disabled={historyStep === 'busy'}>취소</button></div>
          : <button type="button" className="button secondary" onClick={() => { setHistoryStep('confirm'); setMessage(''); }} disabled={accountStep === 'busy'}>기록 지우기</button>}
      </div>
      <div className="danger-row">
        <div><h3><UserRoundX size={16}/>회원 탈퇴</h3><p>조회 기록을 먼저 지우고 계정을 지웁니다. 되돌릴 수 없습니다.</p>
          {(accountStep === 'confirm' || accountStep === 'busy') && <div className="form-field confirm-field"><label htmlFor="withdraw-confirm">계속하려면 <strong>탈퇴</strong>를 입력하세요</label><input id="withdraw-confirm" value={typed} onChange={e => setTyped(e.target.value)} autoComplete="off" disabled={accountStep === 'busy'}/></div>}</div>
        {accountStep === 'confirm' || accountStep === 'busy'
          ? <div className="danger-actions"><button type="button" className="button danger" onClick={() => void removeAccount()} disabled={typed.trim() !== '탈퇴' || accountStep === 'busy'}>{accountStep === 'busy' ? <LoaderCircle size={15} className="spin"/> : <UserRoundX size={15}/>}탈퇴하기</button><button type="button" className="button secondary" onClick={() => { setAccountStep('idle'); setTyped(''); }} disabled={accountStep === 'busy'}>취소</button></div>
          : <button type="button" className="button secondary danger-outline" onClick={() => { setAccountStep('confirm'); setMessage(''); }} disabled={historyStep === 'busy'}>탈퇴</button>}
      </div>
    </>}
    {message && <p role="status" className="account-message">{message}</p>}
    {error && <p role="alert" className="request-error">{error}</p>}
  </section>;
}
