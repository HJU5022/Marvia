'use client';
/** 지켜보는 배 목록 (/watch 화면 지도 아래). B/L 없이 배(MMSI)만 지켜보는 줄이다.
 *
 * 화물 지도(WatchMap)와 섞지 않고 따로 둔 이유: 지도는 B/L 화물의 판정·통관 줄로 이루어져 있어, 판정이 없는 줄을 같은 목록에
 * 넣으면 "판정이 비었다"로 읽힌다. 그래서 줄마다 "배만 지켜보는 중 (B/L 없음, 판정 없음)"을 분명히 달고, 마지막으로 받은 위치만 글로 보인다.
 * 위치는 수집 워커가 받아 둔 값이다(없으면 "아직 위치를 받지 못했어요"). 도착 예정·목적지는 채팅에서 본 글 그대로이고 실시간이 아니다.
 * 해제 버튼은 줄마다 있다. 한 척도 없으면 아무것도 그리지 않는다 (B/L 화물 화면이 그대로 보이게).
 */
import {useEffect, useState} from 'react';
import {EyeOff} from 'lucide-react';
import {dateTime, timeOrRaw} from '@/lib/format';
import {listWatchedVessels, onVesselWatchChange, unwatchVessel, vesselWatchEnabled, type WatchedVessel} from '@/lib/watchVessel';

export function WatchedVessels() {
  const [items, setItems] = useState<WatchedVessel[] | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<number | null>(null);

  useEffect(() => {
    if (!vesselWatchEnabled) return;
    let alive = true;
    const load = () => listWatchedVessels().then(l => { if (alive) setItems(l); }).catch(e => { if (alive) setError(e instanceof Error ? e.message : '지켜보는 배를 불러오지 못했어요.'); });
    void load();
    const off = onVesselWatchChange(() => void load());
    return () => { alive = false; off(); };
  }, []);

  async function remove(mmsi: number) {
    setBusy(mmsi); setError('');
    try { await unwatchVessel(mmsi); } catch (e) { setError(e instanceof Error ? e.message : '지켜보기를 해제하지 못했어요.'); }
    finally { setBusy(null); }
  }

  if (!vesselWatchEnabled || (!items?.length && !error)) return null;
  return <section className="watched-vessels" aria-labelledby="watched-vessels-title">
    <h3 id="watched-vessels-title">지켜보는 배</h3>
    <p role="alert" className="request-error">{error}</p>
    <ul>
      {(items ?? []).map(v => <li key={v.mmsi}>
        <div className="wv-main">
          <strong>{v.name}{v.flag ? ` · ${v.flag}` : ''}</strong>
          <span className="subtle-badge">배만 지켜보는 중 (B/L 없음, 판정 없음)</span>
          <span className="wv-line">{v.lat != null && v.lng != null
            ? `마지막 위치 ${v.lat.toFixed(2)}, ${v.lng.toFixed(2)}${v.sog != null ? ` · ${v.sog}노트` : ''} (${dateTime(v.position_at, true)} 수신)`
            // 위치가 없으면 없다고 분명히 쓰고, 마지막으로 받은 시각이 있으면 그 시각을 같이 적는다
            : `아직 위치를 받지 못했어요. 받는 대로 여기에 나와요.${v.position_at ? ` (마지막 수신 ${dateTime(v.position_at, true)})` : ''}`}</span>
          {(v.dest || v.eta) && <span className="wv-line">{v.dest ? `목적지 ${v.dest}` : ''}{v.dest && v.eta ? ' · ' : ''}{/* ISO 시각은 "10월 8일 08:00"(한국 시간)으로 */}{v.eta ? `도착 예정 ${timeOrRaw(v.eta)}` : ''} (지켜보기를 켤 때 채팅에 보인 값)</span>}
        </div>
        <button type="button" className="button secondary" onClick={() => void remove(v.mmsi)} disabled={busy === v.mmsi} aria-label={`${v.name} 지켜보기 해제`}>
          <EyeOff size={15}/> 해제</button>
      </li>)}
    </ul>
  </section>;
}
