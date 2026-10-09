'use client';
/** 설정 화면의 "카카오톡 알림" 구역. 카카오톡 "나에게 보내기"를 사용자마다 연결하고, 시험 메시지를 보내고, 연결을 끊는다 (backend/app/routers/kakao.py).
 *
 * 연결 흐름: "카카오톡 연결"(POST /api/kakao/connect) → 카카오 동의 화면 → /settings/kakao(app/settings/kakao/page.tsx)가 code·state를 받아
 * 서버에 넘김(POST /api/kakao/callback) → 결과 이름을 달아 이 화면(/settings?kakao=결과)으로 돌아온다. 이 구역은 그 결과를 한 번 보여 주고 주소에서 지운다.
 * 카카오가 서버로 바로 돌아오지 않고 /settings/kakao를 거치는 이유: 이 화면이 로그인 출입증을 붙여 보내야 서버가
 * "연결을 시작한 사람 = 지금 로그인한 사람"을 확인할 수 있다. 서버로 바로 오면 출입증이 없어서, 누군가 자기 연결 링크를 보내 주면
 * 내 카카오톡이 그 사람 계정에 붙을 수 있다.
 * 연결 해제는 되돌릴 수 없어서 화면 안에서 한 번 더 확인한다 (AccountPanel과 같은 방식). 오류 문장은 서버가 정한 한국어 안내를 그대로 보여 준다.
 * 키보드·화면 낭독기 사용자를 위해 눌렀을 때 포커스를 옮기고, 결과 글은 늘 있는 status/alert 칸에서만 바꾼다 (MemoryPanel과 같은 방식, focusKeys 아래).
 * 데모 모드와 로그인이 꺼진 서버에는 연결할 계정이 없어 안내만 한다.
 */
import {useEffect, useRef, useState} from 'react';
import {useRouter} from 'next/navigation';
import {LoaderCircle, MessageCircle, Send, Unlink} from 'lucide-react';
import {useApp} from './AppProvider';
import {connectKakao, getKakaoStatus, isLive, sendKakaoTest, unlinkKakao} from '@/lib/api';
import type {KakaoStatus} from '@/lib/types';
import {dateTime} from '@/lib/format';

/** 주소 ?kakao= 로 돌아온 결과 이름별 안내. ok면 성공 글, 아니면 오류 글로 보여 준다. 여기에 없는 값은 무시한다 */
const RESULT_MESSAGES: Record<string, {ok: boolean; text: string}> = {
  connected: {ok: true, text: "카카오톡이 연결됐어요. '시험 메시지 보내기'로 확인해 보세요."},
  denied: {ok: false, text: '카카오 동의를 취소했어요.'},
  expired: {ok: false, text: '연결 시간이 지났어요. 다시 연결해 주세요.'},
  mismatch: {ok: false, text: '연결을 시작한 계정과 지금 로그인한 계정이 달라요. 다시 연결해 주세요.'},
  no_consent: {ok: false, text: "'카카오톡 메시지 전송'에 동의해야 알림을 받을 수 있어요. 다시 연결해 주세요."},
  failed: {ok: false, text: '연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.'},
};

export function KakaoPanel() {
  const {authEnabled, user} = useApp();
  const router = useRouter();
  const [status, setStatus] = useState<KakaoStatus | null>(null);
  const [loading, setLoading] = useState(false);
  // 누른 요청이 끝날 때까지 다른 버튼을 막는다. ''이면 진행 중인 요청이 없다
  const [busy, setBusy] = useState<'' | 'connect' | 'test' | 'unlink'>('');
  const [unlinkStep, setUnlinkStep] = useState<'idle' | 'confirm'>('idle');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  // 다음 그림이 그려진 뒤 포커스를 줄 곳. data-focus 이름을 앞에서부터 찾아 처음 있는 것에 준다 (없으면 다음 후보)
  const [focusKeys, setFocusKeys] = useState<string[]>([]);
  const sectionRef = useRef<HTMLElement>(null);

  // 실제 모드 + 로그인한 사람만 연결할 수 있다
  const usable = isLive && authEnabled && !!user;

  // 포커스 옮기기: 누른 버튼이 사라지거나 바뀌면 키보드 사용자는 문서 맨 위로 튕긴다. 그림이 다 그려진 뒤 한 번만 옮긴다
  useEffect(() => {
    if (focusKeys.length === 0 || loading) return;
    for (const key of focusKeys) {
      const el = sectionRef.current?.querySelector<HTMLElement>(`[data-focus="${CSS.escape(key)}"]`);
      if (el) { el.focus(); break; }
    }
    setFocusKeys([]);
  }, [focusKeys, loading, status, unlinkStep]);

  // 카카오에서 돌아온 결과(?kakao=)를 한 번 보여 주고 주소에서 지운다. 새로고침해도 같은 글이 다시 뜨지 않게
  useEffect(() => {
    const result = new URLSearchParams(window.location.search).get('kakao');
    if (result === null) return;
    const known = RESULT_MESSAGES[result];
    if (known) { if (known.ok) setMessage(known.text); else setError(known.text); }
    router.replace('/settings');
  }, [router]);

  // 연결 상태 읽기. 실패해도 위의 결과 글은 지우지 않는다 (오류만 덮어쓴다)
  useEffect(() => {
    if (!usable) return;
    let alive = true;
    setLoading(true);
    getKakaoStatus()
      .then(s => { if (alive) setStatus(s); })
      .catch(e => { if (alive) setError(e instanceof Error ? e.message : '카카오톡 연결 상태를 불러오지 못했어요.'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [usable]);

  async function connect() {
    setBusy('connect'); setError(''); setMessage('');
    try {
      const {url} = await connectKakao();
      window.location.assign(url);  // 카카오 동의 화면으로 넘어간다. 페이지가 바뀌므로 busy는 풀지 않는다
    } catch (e) { setError(e instanceof Error ? e.message : '카카오톡 연결을 시작하지 못했어요.'); setBusy(''); }
  }

  async function sendTest() {
    setBusy('test'); setError(''); setMessage('');
    try { await sendKakaoTest(); setMessage('카카오톡으로 시험 메시지를 보냈어요. 휴대폰을 확인해 보세요.'); }
    catch (e) { setError(e instanceof Error ? e.message : '시험 메시지를 보내지 못했어요.'); }
    finally { setBusy(''); }
  }

  async function unlink() {
    setBusy('unlink'); setError(''); setMessage('');
    try {
      await unlinkKakao();
      setStatus(s => s && {...s, linked: false}); setUnlinkStep('idle');
      setMessage('카카오톡 연결을 해제했어요.'); setFocusKeys(['connect', 'status']);
    } catch (e) { setError(e instanceof Error ? e.message : '연결을 해제하지 못했어요.'); setFocusKeys(['unlink-confirm']); }
    finally { setBusy(''); }
  }

  return <section ref={sectionRef} className="st-card kakao-panel" aria-labelledby="kakao-title">
    <h2 id="kakao-title">카카오톡 알림</h2>
    {!usable ? <p className="st-note account-off">{!isLive
      ? '체험 모드에는 연결할 실제 카카오톡이 없어요.'
      : !authEnabled
        ? '지금은 로그인 기능이 꺼져 있어 카카오톡을 연결할 수 없어요.'
        : '로그인하면 카카오톡 알림을 연결할 수 있어요.'}</p>
    : <>
      {/* 실제 연결 상태가 이 구역에서 가장 큰 글이다. 서버가 보낸 값(linked)만 따르고, 상태를 모르면 "연결됨"이라고 하지 않는다 */}
      {loading && !status && <p className="kakao-state pending"><LoaderCircle size={18} className="spin"/> 연결 상태를 확인하는 중</p>}
      {status && !status.configured && <p className="kakao-state off">사용할 수 없음<small>카카오 연결이 아직 준비되지 않아 쓸 수 없어요.</small></p>}
      {status && status.configured && !status.linked && <>
        <p className="kakao-state off">연결되지 않음</p>
        <div className="kakao-actions">
          <button type="button" className="button primary" data-focus="connect" onClick={() => void connect()} disabled={busy !== ''}>
            {busy === 'connect' ? <LoaderCircle size={16} className="spin"/> : <MessageCircle size={16}/>}카카오톡 연결</button>
        </div>
      </>}
      {status && status.configured && status.linked && <>
        <p className="kakao-state on">연결됨</p>
        {/* 서버가 값을 보낸 것만 보여 준다. 아직 보낸 적이 없으면 마지막 발송 줄은 없다 (M7) */}
        {(status.linked_at || status.last_sent_at) && <p className="st-sub kakao-times">
          {status.linked_at && <>{dateTime(status.linked_at, true)}에 연결</>}
          {status.linked_at && status.last_sent_at && ' · '}
          {status.last_sent_at && <>{dateTime(status.last_sent_at, true)}에 마지막으로 보냄</>}</p>}
        <div className="kakao-actions">
          <button type="button" className="button secondary" data-focus="test" onClick={() => void sendTest()} disabled={busy !== ''}>
            {busy === 'test' ? <LoaderCircle size={16} className="spin"/> : <Send size={16}/>}시험 메시지 보내기</button>
        </div>
        {/* 연결 해제는 조용한 줄로 아래에 둔다. 누르면 [취소][연결 해제하기] 순서로 확인을 받는다 */}
        <div className="st-danger-row">
          <p id="kakao-unlink-desc">카카오톡 연결을 끊고 저장해 둔 연결 정보를 지워요. 알림을 다시 받으려면 새로 연결해야 해요.</p>
          {unlinkStep === 'idle'
            ? <button type="button" className="button secondary danger-outline" data-focus="unlink-start" aria-describedby="kakao-unlink-desc" disabled={busy !== ''}
                onClick={() => { setUnlinkStep('confirm'); setMessage(''); setFocusKeys(['unlink-confirm']); }}>연결 해제</button>
            : <div className="danger-actions">
                <button type="button" className="button secondary" disabled={busy !== ''}
                  onClick={() => { setUnlinkStep('idle'); setFocusKeys(['unlink-start']); }}>취소</button>
                <button type="button" className="button danger" data-focus="unlink-confirm" aria-describedby="kakao-unlink-desc"
                  onClick={() => void unlink()} disabled={busy !== ''}>
                  {busy === 'unlink' ? <LoaderCircle size={16} className="spin"/> : <Unlink size={16}/>}연결 해제하기</button>
              </div>}
        </div>
      </>}
    </>}
    {/* 칸은 처음부터 있고 글만 바뀐다. 나중에 생긴 칸은 화면 낭독기가 읽지 않는 경우가 있다. 비어 있을 때는 CSS(:empty)로 안 보이게 한다 */}
    <p role="status" className="account-message" data-focus="status" tabIndex={-1}>{message}</p>
    <p role="alert" className="request-error">{error}</p>
  </section>;
}
