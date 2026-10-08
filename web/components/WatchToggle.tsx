'use client';
/** 지도 위 작은 카드 안의 "지켜보기" 칸 (예전에는 판정 카드 바로 아래). 켜 두면 판정이 바뀐 것을 다음 접속 때 알리고, 카카오톡을 연결했으면 카톡으로도 보낸다 (backend 지켜보기 API).
 *
 * 흐름: 마운트될 때 상태를 읽는다(POST /api/cargo/watch/state) → 버튼으로 켜고 끈다(PUT /api/cargo/watch).
 * 상태를 읽고도 바로 버튼을 못 보이는 이유: 조회 결과의 화물 기록은 응답을 준 뒤 서버가 비동기로 저장한다.
 * 그래서 방금 조회한 직후에는 saved가 false일 수 있다. 1.5초, 3초 간격으로 두 번 더 읽어 보고, 그래도 false면 버튼을 그대로 보인다
 * (그때 누르면 서버가 "잠시 뒤 다시 눌러 주세요"로 알려 주고, 그 문장을 그대로 보여 준다).
 * B/L 번호는 URL이 아니라 요청 본문으로만 보내고(api.ts), 이 화면의 글에도 번호를 쓰지 않는다 (마스킹 값은 상위 카드가 이미 보인다).
 * 새 결과(trace_id)마다 page.tsx가 key를 바꿔 이 칸이 처음 상태로 다시 시작한다.
 * 키보드·화면 낭독기: 버튼은 켜짐/꺼짐이 바뀌어도 같은 요소로 남아 포커스를 잃지 않고, 결과 글은 늘 있는 status/alert 칸에서만 바꾼다 (KakaoPanel과 같은 방식).
 * 대화로 켜고 끈 결과는 AppProvider의 watching으로 받아 같은 상태를 보인다.
 * 출처: G5 작업 리스트. 데모 모드·로그인이 꺼진 서버·비로그인에서는 page.tsx가 아예 그리지 않는다.
 */
import {useEffect, useRef, useState} from 'react';
import {Eye, EyeOff, LoaderCircle} from 'lucide-react';
import {getWatchState, setWatch, watchKey} from '@/lib/api';
import {useApp} from './AppProvider';
import {InfoTip} from './VerdictCard';

/** 저장 전(saved=false)일 때 다시 읽기까지 기다리는 시간. 두 번 기다리고도 false면 버튼을 보인다 */
const SAVE_RETRY_DELAYS_MS = [1500, 3000];

export function WatchToggle({blNo}: {blNo: string}) {
  const {watching: shared, setWatching: share} = useApp();
  const [loading, setLoading] = useState(true);
  const [watching, setWatching] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  // 상태 읽기가 실패했을 때 "다시 불러오기"를 누르면 올라가서 아래 effect를 다시 돌린다
  const [reload, setReload] = useState(0);
  // 상태를 읽지 못했나. 이때는 켜기/끄기 대신 다시 불러오기만 보인다 (현재 상태를 모른 채 버튼을 보이면 반대로 알려 줄 수 있다)
  const [stateFailed, setStateFailed] = useState(false);
  // 누르는 동안 버튼이 disabled가 되면 브라우저가 포커스를 문서 맨 위로 보낸다. 요청이 끝나면 같은 버튼으로 되돌린다
  const buttonRef = useRef<HTMLButtonElement>(null);
  const refocus = useRef(false);
  useEffect(() => {
    if (!busy && refocus.current) { refocus.current = false; buttonRef.current?.focus(); }
  }, [busy]);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setLoading(true); setStateFailed(false); setError('');
    async function read(attempt: number) {
      try {
        const s = await getWatchState(blNo);
        if (!alive) return;
        if (!s.saved && attempt < SAVE_RETRY_DELAYS_MS.length) {
          timer = setTimeout(() => void read(attempt + 1), SAVE_RETRY_DELAYS_MS[attempt]);
          return;
        }
        setWatching(s.watch); share(blNo, s.watch); setLoading(false);
      } catch (e) {
        if (!alive) return;
        setError(e instanceof Error ? e.message : '지켜보기 상태를 불러오지 못했어요.'); setStateFailed(true); setLoading(false);
      }
    }
    void read(0);
    return () => { alive = false; clearTimeout(timer); };
  }, [blNo, reload]);

  // 대화로 켜고 끈 결과(말풍선 버튼, "응")가 오면 이 버튼도 새로고침 없이 따라간다
  const sharedNow = shared[watchKey(blNo)];
  useEffect(() => { if (sharedNow !== undefined) setWatching(sharedNow); }, [sharedNow]);

  async function toggle() {
    const next = !watching;
    setBusy(true); setError(''); setMessage(''); refocus.current = true;
    try {
      const r = await setWatch(blNo, next);
      setWatching(r.watch); share(blNo, r.watch);
      setMessage(r.watch ? '이제 이 화물을 지켜봐요.' : '지켜보기를 껐어요.');
    } catch (e) { setError(e instanceof Error ? e.message : '지켜보기를 바꾸지 못했어요.'); }
    finally { setBusy(false); }
  }

  // 지도 위 작은 카드 안에 들어가는 작은 칸이다 (마누스 시안 3-4). 상태는 실제 서버 값만 보이고, 켜져 있으면 "지켜보는 중" 배지를 분명히 단다.
  // 켜짐/꺼짐 설명 문장은 ⓘ 뒤로 접었다 (사용법 문장은 화면에 늘어놓지 않는다). 버튼 글자는 짧게 두고 낭독용 이름은 원래 문구를 쓴다
  return <section className="watch-toggle" aria-label="화물 지켜보기">
    <div className="watch-row">
      {loading ? <p className="muted"><LoaderCircle size={14} className="spin"/> 지켜보기 상태를 확인하는 중</p>
      : stateFailed ? <button type="button" className="button secondary" onClick={() => setReload(n => n + 1)}>다시 불러오기</button>
      : <>
        {watching && <span className="subtle-badge watching-badge">지켜보는 중</span>}
        <button type="button" ref={buttonRef} className={watching ? 'button secondary' : 'button primary'} aria-label={watching ? '지켜보기 끄기' : '이 화물 지켜보기'} onClick={() => void toggle()} disabled={busy}>
          {busy ? <LoaderCircle size={15} className="spin"/> : watching ? <EyeOff size={15}/> : <Eye size={15}/>}
          {watching ? '끄기' : '지켜보기'}</button>
        <InfoTip label="지켜보기 설명">판정이 바뀌면 다음에 접속할 때 알려 드리고, 카카오톡을 연결했다면 카톡으로도 보내 드려요.</InfoTip>
      </>}
    </div>
    {/* 칸은 처음부터 있고 글만 바뀐다. 나중에 생긴 칸은 화면 낭독기가 읽지 않는 경우가 있다. 비어 있을 때는 CSS(:empty)로 안 보이게 한다 */}
    <p role="status" className="account-message" tabIndex={-1}>{message}</p>
    <p role="alert" className="request-error">{error}</p>
  </section>;
}
