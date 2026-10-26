'use client';
/** 로그인 전 첫 화면 = 소개 랜딩. 사이드바 없이 전체 화면으로 나온다(Shell).
 * 본문은 /about 과 같은 IntroContent. 시작 버튼이 구글 로그인이다. 비밀번호 입력 칸은 두지 않는다. 로그인 기능이 꺼진 환경(채점용)에서는 이 화면이 나오지 않는다.
 * 체험 모드 버튼은 두지 않는다 (배포 화면에는 불필요, 체험 데모는 e2e용으로 코드에만 남아 있다).
 * 데모 계정이 설정돼 있으면 "데모 계정으로 둘러보기" 버튼과 계정 표기를 같이 보여 준다 (docs/specs/demo-account.md).
 * [왜] 로그인이 필수라 자기 Google 계정을 쓰기 싫은 사람(채용 담당자 등)도 기능을 써 볼 수 있어야 한다.
 * 로그인 로직(signInWithGoogle)은 G3 때 그대로다. 스타일은 app/styles/landing.css.
 * 하단에는 약관 링크를 두지 않는다. 우리 서비스에 따로 정한 약관·처리방침 문서가 없다.
 */
import {useState} from 'react';
import {LoaderCircle} from 'lucide-react';
import {demoAccount, signInWithDemo, signInWithGoogle} from '@/lib/auth';
import {IntroContent} from './IntroContent';

export function LoginScreen() {
  // 어느 버튼을 눌렀는지. 누른 버튼에만 도는 표시를 붙이고, 그동안 두 버튼을 다 막는다
  const [busy, setBusy] = useState<'' | 'google' | 'demo'>('');
  const [error, setError] = useState('');

  async function start() {
    setBusy('google'); setError('');
    try { await signInWithGoogle(); }  // 성공하면 구글로 페이지가 넘어간다
    catch (e) { setError(e instanceof Error ? e.message : '로그인을 시작하지 못했어요.'); setBusy(''); }
  }

  async function startDemo() {
    setBusy('demo'); setError('');
    try { await signInWithDemo(); }  // 성공하면 페이지 이동 없이 onAuthChange가 앱 화면으로 바꾼다
    catch (e) { setError(e instanceof Error ? e.message : '데모 계정으로 로그인하지 못했어요.'); setBusy(''); }
  }

  // 큰 버튼(소개 본문 위·아래)과 맨 위 작은 로그인이 같은 동작을 부른다
  const action = <>
    <button type="button" className="intro-btn" onClick={start} disabled={busy !== ''}>
      {busy === 'google' ? <LoaderCircle size={16} className="spin"/> : <GoogleMark/>}{busy === 'google' ? '구글로 이동 중' : 'Google로 시작하기'}
    </button>
    {demoAccount && <button type="button" className="intro-btn intro-btn-demo" onClick={startDemo} disabled={busy !== ''}>
      {busy === 'demo' && <LoaderCircle size={16} className="spin"/>}{busy === 'demo' ? '로그인 중' : '데모 계정으로 둘러보기'}
    </button>}
    {/* [주의] 공개 데모 계정이라 비밀번호를 그대로 적는다. 다른 곳에서 쓰는 비밀번호를 넣으면 안 된다 */}
    {demoAccount && <p className="intro-demo-note">데모 계정 · {demoAccount.email} / {demoAccount.password}</p>}
    {error && <p role="alert" className="intro-error">{error}</p>}
  </>;
  // 윗줄 오른쪽 작은 로그인 (엘레강스: 글자만, 같은 동작)
  const navRight = <button type="button" className="intro-nav-login" onClick={start} disabled={busy !== ''}>로그인</button>;
  return <IntroContent action={action} navRight={navRight} footer={<footer className="intro-foot">© 2026 Marvia</footer>}/>;
}

/** 구글 로고. 외부 이미지를 부르지 않으려고 SVG로 둔다. */
function GoogleMark() {
  return <svg className="g-mark" width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
    <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/>
    <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
    <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/>
    <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z"/>
  </svg>;
}
