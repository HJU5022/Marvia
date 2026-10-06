'use client';
/** 입항 예정 선박 자세히 보기 (docs/specs/chat-search.md "선박 자세히 보기"). 선박 표에서 선명을 누르면 행 아래에 펼친다.
 * GET /api/vessels/detail 한 번으로 해수부 일정, AIS 위치, 부산까지 거리를 받는다. 판정은 하지 않는다.
 * 값 칸은 보통 글꼴이다. 한국어(확인되지 않음, 노트, 해리)가 고정폭 글꼴로 보이지 않게 한다 (10-02 UI 점검 V4).
 * 지도는 자세히 보기 전용 VesselMap(배 중심 확대, 진행 방향, 남은 예상 바닷길). 위치 신선도는 서버가 rules.md로 정한 값이다.
 */
import {useEffect, useState} from 'react';
import {Anchor, LoaderCircle, Navigation, TriangleAlert} from 'lucide-react';
import {VesselMap} from './VesselMap';
import {getVesselDetail} from '@/lib/api';
import {countryLabel, dateTime, portLabel, shown} from '@/lib/format';
import type {VesselDetailResponse, VesselItem} from '@/lib/types';

const SOURCE_LABEL: Record<string, string> = {mof: '해수부 입항 일정', shipfinder: '선박 위치', searoute: '남은 거리 계산'};
// 출처별 실패 안내. 서버 message에는 엔드포인트·키 이름·예외명이 섞여 있어 화면에 내지 않고 고정 문구만 쓴다 (10-02 화면 용어 점검)
const SOURCE_FAIL: Record<string, string> = {mof: '지금 받지 못했어요', shipfinder: '지금 받지 못했어요', searoute: '계산하지 못했어요'};


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
  if (!data) return <div className="vessel-detail"><div className="empty-inline"><LoaderCircle size={16} className="spin"/>해수부 일정과 선박 위치를 불러오는 중</div></div>;

  const p = data.position, s = data.schedule, d = data.distance, v = data.vessel;
  return <div className="vessel-detail">
    <div className="vessel-detail-grid">
      <div className="vessel-detail-map">{p ? <VesselMap name={vessel.ship_name} lat={p.lat} lng={p.lng} sog={p.sog} cog={p.cog} freshness={p.freshness} lastTime={p.last_time} route={p.route ?? []} distanceNm={d?.distance_nm ?? null}/> : <div className="empty-state"><Navigation/><h2>선박 위치를 받지 못했습니다.</h2></div>}</div>
      <div className="vessel-detail-info">
        <section><h4><Navigation size={14}/>선박 위치(실시간) {p && <span className={`fresh-chip ${p.freshness}`}>{p.freshness === 'fresh' ? '수신 정상' : p.freshness === 'stale' ? '오래된 위치' : '수신 시각 확인 안 됨'}</span>}</h4>
          <dl>{([
            ['선박 식별 번호 · 국적', v ? `${v.mmsi} · ${countryLabel(v.flag)}` : null],
            ['좌표', p ? `${p.lat.toFixed(3)} N / ${p.lng.toFixed(3)} E` : null],
            ['속력 · 진행 방향', p ? `${shown(p.sog)}노트 · ${shown(p.cog)}°` : null],
            ['선박이 밝힌 목적지', p?.dest ? portLabel(p.dest) : null],
            ['선박이 보낸 도착 예정', p?.ais_eta ? dateTime(p.ais_eta) : null],
            ['마지막 수신', p?.last_time ? dateTime(p.last_time) : null],
          ] as const).map(([k, x]) => <div key={k}><dt>{k}</dt><dd className={x == null ? 'unknown' : undefined}>{shown(x)}</dd></div>)}</dl>
        </section>
        <section><h4><Anchor size={14}/>부산항 일정 (해수부)</h4>
          <dl>{([
            ['입항 예정', s?.planned_arrival ? dateTime(s.planned_arrival) : null],
            ['입항 실적', s?.actual_arrival ? dateTime(s.actual_arrival) : null],
            ['접안 시설', s?.facility ?? vessel.facility],
            ['부산까지', d ? `${d.distance_nm} 해리${d.calc_hours_at_sog != null ? ` · 지금 속력이면 약 ${Math.round(d.calc_hours_at_sog)}시간` : ''}` : null],
            ['지금 속력 기준 예상 도착', d?.calc_eta ? dateTime(d.calc_eta) : null],
          ] as const).map(([k, x]) => <div key={k}><dt>{k}</dt><dd className={x == null ? 'unknown' : undefined}>{shown(x)}</dd></div>)}</dl>
          {s && s.control_events.length > 0 && <ol className="control-events">{s.control_events.map((e, i) =>
            <li key={i}><strong>{e.kind}</strong><span className="mono">{dateTime(e.at)}</span><small>{shown(e.facility)}</small></li>)}</ol>}
        </section>
        {data.errors.length > 0 && <div className="info-note"><TriangleAlert size={15}/><span>{data.errors.map(e => `${SOURCE_LABEL[e.source] ?? '일부 정보'}: ${SOURCE_FAIL[e.source] ?? '지금 받지 못했어요'}`).join(' · ')}</span></div>}
        <p className="help-text">지금 속력 기준 예상 도착은 지금 속력을 끝까지 유지한다는 가정입니다. 판정이 아니며, 내 화물은 B/L 번호로 물어보세요.</p>
      </div>
    </div>
  </div>;
}
