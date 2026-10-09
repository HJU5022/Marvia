'use client';
/** 채팅에서 본 배 옆에 놓는 "이 배 지켜보기" 아이콘 버튼. B/L 없이 배(MMSI)만 지켜본다.
 *
 * 흐름: 마운트될 때 내 지켜보는 배 목록을 읽어 이 배가 들어 있는지 정한다 → 누르면 켜고(POST) 다시 누르면 끈다(DELETE).
 * 같은 화면의 버튼이 여럿이어도 목록 요청은 한 번만 나가도록 짧게 묶는다(SHARE_MS). 켜고 끈 일은 lib/watchVessel.ts가 다른 버튼에 알린다.
 * 판정·통관은 없다. 켜면 /watch 화면에 "배만 지켜보는 중"으로 올라가 마지막 위치를 보여 준다.
 * 호출부호만 있는 버튼(입항 예정 목록)은 MMSI를 몰라 목록에서 찾을 수 없다: 올리기 전에는 "안 지켜봄"으로 보이고, 올린 뒤 서버가 준 MMSI를
 * 컴포넌트 안에 들고 있다가 해제에 쓴다. 새로 고침하면 다시 "안 지켜봄"이 되지만 다시 눌러도 같은 배의 값만 갱신된다.
 * 체험 모드(서버 없음)·상태를 못 읽었을 때는 그리지 않는다: 현재 상태를 모른 채 버튼을 보이면 반대로 알려 줄 수 있다.
 * 결과 글은 늘 있는 status/alert 칸에서만 바꾼다 (WatchToggle과 같은 방식, 화면 낭독기). 시각적으로는 숨기고 낭독만 한다.
 */
import {useEffect, useRef, useState} from 'react';
import {Eye, EyeOff, LoaderCircle} from 'lucide-react';
import {listWatchedVessels, onVesselWatchChange, unwatchVessel, vesselWatchEnabled, watchVessel, type WatchedVessel} from '@/lib/watchVessel';

export interface WatchVesselButtonProps {
  /** 배 번호(MMSI). 없으면 callSign으로 올린다 */
  mmsi?: number | null;
  /** 호출부호. MMSI가 없는 입항 예정 목록용. 서버가 찾아 정하고, 못 찾으면 안내 문장이 뜬다 */
  callSign?: string | null;
  /** 채팅에 보인 배 이름 */
  name: string;
  /** 채팅에 보인 국적 (없으면 생략) */
  flag?: string | null;
  /** 채팅에 보인 목적지 글 (없으면 생략) */
  dest?: string | null;
  /** 채팅에 보인 도착 예정 글 (없으면 생략) */
  eta?: string | null;
}

// 버튼 여러 개가 한꺼번에 마운트돼도 목록은 한 번만 읽는다
const SHARE_MS = 1000;
let shared: {at: number; promise: Promise<WatchedVessel[]>} | null = null;
function readList(fresh: boolean): Promise<WatchedVessel[]> {
  if (fresh || !shared || Date.now() - shared.at > SHARE_MS) shared = {at: Date.now(), promise: listWatchedVessels()};
  return shared.promise;
}

export function WatchVesselButton({mmsi: mmsiProp, callSign, name, flag, dest, eta}: WatchVesselButtonProps) {
  const [found, setFound] = useState<number | null>(null);  // 호출부호로 올린 뒤 서버가 정한 MMSI
  const mmsi = mmsiProp || found;
  const [watching, setWatching] = useState<boolean | null>(mmsiProp || !callSign ? null : false);  // null: 아직 모른다
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const buttonRef = useRef<HTMLButtonElement>(null);
  const refocus = useRef(false);
  // 오류는 이름 아래 작은 글로만 보이고 5초 뒤 사라진다 (전에는 큰 분홍 상자가 줄 모양을 깨뜨렸다)
  useEffect(() => { if (!error) return; const t = window.setTimeout(() => setError(''), 5000); return () => window.clearTimeout(t); }, [error]);
  useEffect(() => { if (!busy && refocus.current) { refocus.current = false; buttonRef.current?.focus(); } }, [busy]);

  useEffect(() => {
    if (!vesselWatchEnabled || !mmsi) return;
    let alive = true;
    const load = (fresh: boolean) => readList(fresh).then(l => { if (alive) setWatching(l.some(v => v.mmsi === mmsi)); }).catch(() => { /* 못 읽으면 버튼을 안 그린다 */ });
    void load(!mmsiProp);  // 호출부호로 방금 올린 배는 막 바뀐 목록을 새로 읽는다
    const off = onVesselWatchChange(() => void load(true));  // 다른 버튼·목록에서 바꾼 것을 따라간다
    return () => { alive = false; off(); };
  }, [mmsi, mmsiProp]);

  async function toggle() {
    setBusy(true); setError(''); refocus.current = true;
    try {
      if (watching && mmsi) await unwatchVessel(mmsi);
      else if (!watching) { const m = await watchVessel({mmsi, callSign, name, flag, dest, eta}); if (!mmsiProp) setFound(m); }
      setWatching(!watching);
    } catch (e) { setError(e instanceof Error ? e.message : '배 지켜보기를 바꾸지 못했어요.'); }
    finally { setBusy(false); }
  }

  if (!vesselWatchEnabled || watching === null) return null;
  const label = watching ? '지켜보기 해제' : '이 배 지켜보기';
  return <span className="watch-vessel-btn">
    <button type="button" ref={buttonRef} className={`icon-button${watching ? ' on' : ''}`} aria-label={label} aria-pressed={watching} title={label}
      onClick={() => void toggle()} disabled={busy}>
      {busy ? <LoaderCircle size={16} className="spin"/> : watching ? <EyeOff size={16}/> : <Eye size={16}/>}
    </button>
    <span role="alert" className="wv-err">{error}</span>
  </span>;
}
