'use client';
/** 대화 말풍선 아래의 "지켜보기" 제안 버튼. 에이전트가 watch_offer를 주면 말풍선 글 아래에 작게 붙는다.
 * 제안 문장(reason)은 서버가 코드로 써서 reply 안에 이미 있으므로 여기서 다시 쓰지 않는다. 버튼만 그린다.
 * 로그인했으면 결과 칸의 "이 화물 지켜보기"(WatchToggle)와 같은 API(PUT /api/cargo/watch)를 부른다. 로그인이 풀렸으면 로그인으로 보낸다.
 * 켜짐 여부는 AppProvider의 watching을 같이 본다. 그래서 "응"이라고 답해 서버가 켰을 때(watch_set)나 결과 칸 버튼으로 켰을 때도 이 버튼이 "지켜보는 중"으로 바뀐다.
 * 오류는 WatchToggle과 같게 서버 안내 문장을 그대로 보여 준다 (401 로그인, 400/409 한도, 503 잠시 뒤).
 */
import {useState} from 'react';
import {Eye, LoaderCircle} from 'lucide-react';
import {useApp} from './AppProvider';
import {setWatch, watchKey} from '@/lib/api';
import {signInWithGoogle} from '@/lib/auth';
import type {WatchOffer} from '@/lib/types';

export function WatchOfferAction({offer}: {offer: WatchOffer}) {
  const {user, authEnabled, watching, setWatching} = useApp();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const on = watching[watchKey(offer.bl_no)] === true;
  // 서버가 본 로그인 여부보다 지금 화면의 로그인 상태를 우선한다 (그 사이 로그인했거나 세션이 풀렸을 수 있다)
  const loggedIn = !!user;

  async function start() {
    setBusy(true); setError('');
    try {
      if (!loggedIn) { await signInWithGoogle(); return; }  // 성공하면 구글로 페이지가 넘어간다
      const r = await setWatch(offer.bl_no, true);
      setWatching(offer.bl_no, r.watch);
    } catch (e) { setError(e instanceof Error ? e.message : '지켜보기를 켜지 못했어요. 잠시 뒤 다시 눌러 주세요.'); }
    finally { setBusy(false); }
  }

  if (on) return <div className="watch-offer"><span className="subtle-badge" role="status">지켜보는 중</span></div>;
  // 로그인 기능이 꺼진 서버에서는 로그인할 곳이 없다. 눌러도 되지 않는 버튼을 보이지 않는다
  if (!loggedIn && !authEnabled) return null;
  return <div className="watch-offer">
    <button type="button" className="button primary" onClick={() => void start()} disabled={busy}>
      {busy ? <LoaderCircle size={15} className="spin"/> : <Eye size={15}/>}{loggedIn ? '지켜보기' : '로그인하고 지켜보기'}</button>
    <p role="alert" className="request-error">{error}</p>
  </div>;
}
