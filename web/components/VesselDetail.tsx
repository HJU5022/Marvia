'use client';
/** 입항 예정 선박 자세히 보기 (docs/specs/chat-search.md "선박 자세히 보기"). 선박 표에서 선명을 누르면 행 아래에 펼친다.
 * GET /api/vessels/detail 한 번으로 해수부 일정, AIS 위치, 부산까지 거리를 받는다. 판정은 하지 않는다.
 * 지도는 화물 화면의 MapPanel을 그대로 쓴다(위치와 선명만 읽는다). 위치 신선도는 서버가 rules.md로 정한 값이다.
 */
import {useEffect, useState} from 'react';
import {Anchor, LoaderCircle, Navigation, TriangleAlert} from 'lucide-react';
import {MapPanel} from './MapPanel';
import {getVesselDetail} from '@/lib/api';
import {dateTime, shown} from '@/lib/format';
import type {AgentResponse, VesselDetailResponse, VesselItem} from '@/lib/types';

const SOURCE_LABEL: Record<string, string> = {mof: '해양수산부', shipfinder: 'ShipFinder(AIS)', searoute: '해상 거리 계산'};

/** MapPanel은 응답의 position과 vessel.name만 읽는다. 그 두 칸만 채운 모양으로 넘긴다 */
function asMapInput(d: VesselDetailResponse, name: string): AgentResponse | null {
  const p = d.position;
  if (!p) return null;
  return {position: {lat: p.lat, lng: p.lng, sog: p.sog ?? 0, cog: p.cog ?? 0, navistat: p.navistat ?? 0,
    last_time: p.last_time ?? '', freshness: p.freshness}, vessel: {name}} as unknown as AgentResponse;
}

export function VesselDetail({vessel}: {vessel: VesselItem}) {
  const [data, setData] = useState<VesselDetailResponse | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    getVesselDetail(vessel.call_sign, vessel.ship_name)
      .then(d => { if (alive) setData(d); })
      .catch(e => { if (alive) setError(e instanceof Error ? e.message : '자세한 정보를 불러오지 못했습니다.'); });
    return () => { alive = false; };
  }, [vessel.call_sign, vessel.ship_name]);

  if (error) return <div className="vessel-detail"><p role="alert" className="request-error">{error}</p></div>;
  if (!data) return <div className="vessel-detail"><div className="empty-inline"><LoaderCircle size={16} className="spin"/>해수부 일정과 AIS 위치를 불러오는 중</div></div>;

  const p = data.position, s = data.schedule, d = data.distance, v = data.vessel;
  const map = asMapInput(data, vessel.ship_name);
  return <div className="vessel-detail">
    <div className="vessel-detail-grid">
      <div className="vessel-detail-map">{map ? <MapPanel response={map}/> : <div className="empty-state"><Navigation/><h2>AIS 위치를 받지 못했습니다.</h2></div>}</div>
      <div className="vessel-detail-info">
        <section><h4><Navigation size={14}/>실시간 AIS {p && <span className={`fresh-chip ${p.freshness}`}>{p.freshness === 'fresh' ? '수신 정상' : p.freshness === 'stale' ? '오래된 위치' : '신선도 미확인'}</span>}</h4>
          <dl>{([
            ['MMSI · 국적', v ? `${v.mmsi} · ${shown(v.flag)}` : null],
            ['좌표', p ? `${p.lat.toFixed(3)} N / ${p.lng.toFixed(3)} E` : null],
            ['속력 · 침로', p ? `${shown(p.sog)} kn · ${shown(p.cog)}°` : null],
            ['AIS 목적지', p?.dest ?? null],
            ['AIS 도착 예정', p?.ais_eta ? dateTime(p.ais_eta) : null],
            ['마지막 수신', p?.last_time ? dateTime(p.last_time) : null],
          ] as const).map(([k, x]) => <div key={k}><dt>{k}</dt><dd className="mono">{shown(x)}</dd></div>)}</dl>
        </section>
        <section><h4><Anchor size={14}/>부산항 일정 (해수부)</h4>
          <dl>{([
            ['입항 예정', s?.planned_arrival ? dateTime(s.planned_arrival) : null],
            ['입항 실적', s?.actual_arrival ? dateTime(s.actual_arrival) : null],
            ['접안 시설', s?.facility ?? vessel.facility],
            ['부산까지', d ? `${d.distance_nm} 해리${d.calc_hours_at_sog != null ? ` · 지금 속력이면 약 ${Math.round(d.calc_hours_at_sog)}시간` : ''}` : null],
            ['계산 도착', d?.calc_eta ? dateTime(d.calc_eta) : null],
          ] as const).map(([k, x]) => <div key={k}><dt>{k}</dt><dd className="mono">{shown(x)}</dd></div>)}</dl>
          {s && s.control_events.length > 0 && <ol className="control-events">{s.control_events.map((e, i) =>
            <li key={i}><strong>{e.kind}</strong><span className="mono">{dateTime(e.at)}</span><small>{shown(e.facility)}</small></li>)}</ol>}
        </section>
        {data.errors.length > 0 && <div className="info-note"><TriangleAlert size={15}/><span>{data.errors.map(e => `${SOURCE_LABEL[e.source] ?? e.source}: ${e.message ?? e.code}`).join(' · ')}</span></div>}
        <p className="help-text">계산 도착은 지금 속력을 끝까지 유지한다는 가정입니다. 판정이 아니며, 내 화물은 B/L 번호로 물어보세요.</p>
      </div>
    </div>
  </div>;
}
