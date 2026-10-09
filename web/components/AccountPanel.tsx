'use client';
/** 설정 화면의 "계정 관리" 구역. 내 기록 삭제(DELETE /api/history)와 회원 탈퇴(DELETE /api/account)를 부른다.
 *
 * 둘 다 되돌릴 수 없어서 한 번 더 확인한다. 브라우저 confirm 창 대신 화면 안에서 확인한다(접근성, 목업 톤).
 * 탈퇴는 "탈퇴"를 직접 입력해야 버튼이 켜진다. 실패(503)는 숨기지 않고, 다시 누르면 백엔드가 이어서 끝낸다 (services/account.py).
 * 로그인이 꺼진 환경에는 지울 "내" 기록이 없다. 그 기록은 90일 자동 삭제로 정리된다는 안내만 한다 (routers/history.py).
 */
import {useState} from 'react';
import {LoaderCircle, Trash2, UserRoundX} from 'lucide-react';
import {useApp} from './AppProvider';
import {deleteMyAccount, deleteMyHistory, isLive} from '@/lib/api';
import {signOut} from '@/lib/auth';

type Step = 'idle' | 'confirm' | 'busy' | 'done';

export function AccountPanel() {
  const {authEnabled, user, reset, refreshConversations} = useApp();
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
      setMessage(`조회 이력 ${r.deleted}건과 기억한 화물·메모장·대화 목록을 지웠어요.`); setHistoryStep('done'); reset();
      void refreshConversations();  // 서버는 대화 목록도 지웠다. 사이드바 목록도 다시 읽는다 (지웠는데 목록이 남아 보임)
    } catch (e) { setError(e instanceof Error ? e.message : '이력을 지우지 못했어요.'); setHistoryStep('confirm'); }
  }

  async function removeAccount() {
    setAccountStep('busy'); setError(''); setMessage('');
    try {
      const r = await deleteMyAccount();
      setMessage(`조회 이력 ${r.deleted_records}건과 계정을 지웠어요. 그동안 이용해 주셔서 감사해요.`); setAccountStep('done');
      await signOut(); reset();  // 서버에서 계정이 지워졌으니 브라우저의 로그인 정보도 지운다
    } catch (e) { setError(e instanceof Error ? e.message : '탈퇴를 마치지 못했어요.'); setAccountStep('confirm'); }
  }

  return <div className="st-cols account-stack">
    {!usable ? <p className="st-note account-off">{!isLive
      ? '체험 모드에는 실제 계정과 이력이 없어요.'
      : !authEnabled
        ? '지금은 로그인 기능이 꺼져 있어 이력을 사용자별로 나누지 않아요. 조회 이력은 90일 뒤 자동으로 지워져요.'
        : '로그인하면 내 이력을 지우거나 탈퇴할 수 있어요.'}</p>
    : <>
      <section className="st-card st-danger-card" aria-labelledby="account-title">
        <h2 id="account-title">내 조회 이력 지우기</h2>
        <p className="st-sub">조회 이력, 기억한 화물, 메모, 대화 목록이 모두 지워져요. 되돌릴 수 없어요.</p>
        {historyStep === 'confirm' || historyStep === 'busy'
          ? <div className="st-confirm"><div><strong>정말 내 이력을 지울까요?</strong><span>되돌릴 수 없어요.</span></div>
              <div className="danger-actions"><button type="button" className="button secondary" onClick={() => setHistoryStep('idle')} disabled={historyStep === 'busy'}>취소</button><button type="button" className="button danger" onClick={() => void removeHistory()} disabled={historyStep === 'busy'}>{historyStep === 'busy' ? <LoaderCircle size={16} className="spin"/> : <Trash2 size={16}/>}모두 지우기</button></div></div>
          : <div className="st-actions"><button type="button" className="button secondary danger-outline" onClick={() => { setHistoryStep('confirm'); setMessage(''); }} disabled={accountStep === 'busy'}><Trash2 size={16}/>이력 지우기</button></div>}
      </section>
      {/* 탈퇴는 눈에 덜 띄게 맨 아래에 작은 글자 버튼으로 둔다. 누르면 확인 칸이 열리고 "탈퇴"를 직접 입력해야 켜진다 */}
      <div className="st-span st-withdraw st-withdraw-low">
        {accountStep === 'idle' && <button type="button" className="withdraw-link" onClick={() => { setAccountStep('confirm'); setMessage(''); }} disabled={historyStep === 'busy'}>회원 탈퇴</button>}
        {(accountStep === 'confirm' || accountStep === 'busy') && <div className="withdraw-confirm" role="group" aria-labelledby="withdraw-title">
          <strong id="withdraw-title">정말 탈퇴할까요?</strong>
          <p className="st-sub">조회 이력을 먼저 지우고 계정을 지워요. 되돌릴 수 없고, 탈퇴하면 바로 로그아웃돼요.</p>
          <div className="form-field confirm-field"><label htmlFor="withdraw-confirm">계속하려면 <strong>탈퇴</strong>라고 입력해 주세요</label><input id="withdraw-confirm" value={typed} onChange={e => setTyped(e.target.value)} autoComplete="off" disabled={accountStep === 'busy'}/></div>
          <div className="danger-actions st-actions"><button type="button" className="button secondary" onClick={() => { setAccountStep('idle'); setTyped(''); }} disabled={accountStep === 'busy'}>취소</button><button type="button" className="button danger" onClick={() => void removeAccount()} disabled={typed.trim() !== '탈퇴' || accountStep === 'busy'}>{accountStep === 'busy' ? <LoaderCircle size={16} className="spin"/> : <UserRoundX size={16}/>}탈퇴하기</button></div></div>}
      </div>
    </>}
    {message && <p role="status" className="account-message st-span">{message}</p>}
    {error && <p role="alert" className="request-error st-span">{error}</p>}
  </div>;
}
