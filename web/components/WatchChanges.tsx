'use client';
/** 홈 화면 맨 위의 "지난 접속 뒤 판정이 바뀐 화물" 알림 카드. 지켜보기를 켠 화물의 판정이 바뀌었으면 다음 접속 때 여기서 알린다 (GET /api/watch/changes).
 *
 * 한 줄에 화물 이름(없으면 마스킹 B/L)과 "이전 판정 → 새 판정 (바뀐 시각)"을 보인다. "확인했어요"를 누르면 서버에 확인 처리하고(POST /api/watch/changes/seen)
 * 카드를 닫는다. 서버가 확인 처리해야 다음 접속에 같은 알림이 다시 뜨지 않으므로, 확인 요청이 실패하면 카드를 닫지 않고 오류를 보여 준다.
 * 알림은 덤이라서 목록을 못 읽으면 조용히 아무것도 그리지 않는다(홈 화면의 다른 기능을 막지 않는다). 데모 모드·로그인이 꺼진 서버·비로그인에서는 부르지 않는다.
 * 내용은 서버가 마스킹해 준 B/L만 쓴다. 전체 B/L은 이 화면에 오지 않는다.
 * 출처: G5 작업 리스트, 10-05 결정.
 */
import {useEffect, useState} from 'react';
import {BellRing, Check, LoaderCircle} from 'lucide-react';
import {useApp} from './AppProvider';
import {getWatchChanges, isLive, markWatchChangesSeen} from '@/lib/api';
import {dateTime, verdictLabels} from '@/lib/format';
import type {WatchChange} from '@/lib/types';

export function WatchChanges() {
  const {authEnabled, authReady, user} = useApp();
  const [changes, setChanges] = useState<WatchChange[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const usable = isLive && authEnabled && authReady && !!user;

  // 로그인한 사람이 바뀌면(로그아웃 포함) 다시 읽고, 이전 사람의 목록은 바로 비운다
  useEffect(() => {
    setChanges([]); setError('');
    if (!usable) return;
    let alive = true;
    getWatchChanges().then(c => { if (alive) setChanges(c); }).catch(() => { /* 조용히 실패: 카드를 그리지 않는다 */ });
    return () => { alive = false; };
  }, [usable, user?.id]);

  async function seen() {
    setBusy(true); setError('');
    try { await markWatchChangesSeen(); setChanges([]); }
    catch (e) { setError(e instanceof Error ? e.message : '확인 처리하지 못했습니다. 잠시 뒤 다시 눌러 주세요.'); }
    finally { setBusy(false); }
  }

  if (!usable || changes.length === 0) return null;
  return <section className="watch-changes" aria-labelledby="watch-changes-title">
    <h2 id="watch-changes-title"><BellRing size={16}/>지난 접속 뒤 판정이 바뀐 화물</h2>
    <ul>{changes.map((c, i) => <li key={`${c.bl_masked}-${c.changed_at}-${i}`}>
      <span>{c.label ?? c.bl_masked}</span>: {verdictLabels[c.from_verdict]} → <strong className={`to-${c.to_verdict}`}>{verdictLabels[c.to_verdict]}</strong> <span className="muted">({dateTime(c.changed_at, true)})</span>
    </li>)}</ul>
    <button type="button" className="button secondary" onClick={() => void seen()} disabled={busy}>
      {busy ? <LoaderCircle size={15} className="spin"/> : <Check size={15}/>}확인했어요</button>
    <p role="alert" className="request-error">{error}</p>
  </section>;
}
