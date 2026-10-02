'use client';
/** 로그인 화면 (작업 G3). 백엔드가 로그인을 필수로 두었으므로(09-30, backend/app/auth.py) 로그인 전에는 조회 화면 대신 이것을 보여 준다.
 * 구글 로그인 버튼 하나뿐이다. 비밀번호를 받지 않는다. 로그인 기능이 꺼진 환경(채점용)에서는 이 화면이 나오지 않는다.
 */
import {useState} from 'react';
import {ArrowUpRight, LoaderCircle, LockKeyhole, ShieldCheck, Waves} from 'lucide-react';
import {signInWithGoogle} from '@/lib/auth';

export function LoginScreen() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function start() {
    setBusy(true); setError('');
    try { await signInWithGoogle(); }  // 성공하면 구글로 페이지가 넘어간다
    catch (e) { setError(e instanceof Error ? e.message : '로그인을 시작하지 못했습니다.'); setBusy(false); }
  }

  return <div className="login-page">
    <section className="login-card" aria-labelledby="login-title">
      <div className="login-brand"><span className="brand-symbol"><Waves size={22}/></span><span>marvia<span className="brand-dot">.</span></span></div>
      <span className="eyebrow">SIGN IN TO YOUR CARGO DESK</span>
      <h1 id="login-title">내 화물을 보려면<br/>먼저 로그인해 주세요<span className="accent-dot">.</span></h1>
      <p>조회 기록과 판정은 로그인한 사람에게만 묶입니다. 다른 사람이 내 B/L을 볼 수 없습니다.</p>
      <button type="button" className="button primary login-google" onClick={start} disabled={busy}>
        {busy ? <LoaderCircle size={17} className="spin"/> : <GoogleMark/>}{busy ? '구글로 이동 중' : 'Google 계정으로 계속하기'}
      </button>
      {error && <p role="alert" className="request-error">{error}</p>}
      <ul className="login-points">
        <li><LockKeyhole size={15}/>B/L 원본은 잠가서 저장하고, 화면과 기록에는 뒤 4자리만 보입니다.</li>
        <li><ShieldCheck size={15}/>조회 기록은 90일 뒤 자동으로 지워지고, 설정에서 언제든 지울 수 있습니다.</li>
      </ul>
      <a className="quiet-link" href="/about">Marvia가 무엇인지 먼저 보기 <ArrowUpRight size={14}/></a>
    </section>
  </div>;
}

/** 구글 로고. 외부 이미지를 부르지 않으려고 SVG로 둔다. */
function GoogleMark() {
  return <svg width="17" height="17" viewBox="0 0 48 48" aria-hidden="true">
    <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/>
    <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
    <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/>
    <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"/>
  </svg>;
}
