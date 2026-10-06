'use client';
/** 입항 예정 선박 자세히 보기 (docs/specs/chat-search.md "선박 자세히 보기"). Manus 2-4 시안: 표 아래 카드 하나에
 * 선명 제목 + 설명 + 수신 상태 칩, 왼쪽 지도, 오른쪽 "선박 위치(실시간)"와 "부산항 일정(해수부)" 두 칸.
 * GET /api/vessels/detail 한 번으로 해수부 일정, AIS 위치, 부산까지 거리를 받는다. 판정은 하지 않는다.
 * 값 칸은 보통 글꼴이다. 한국어(확인되지 않음, 노트, 해리)가 고정폭 글꼴로 보이지 않게 한다 (10-02 UI 점검 V4).
 * 지도는 자세히 보기 전용 VesselMap(배 중심 확대, 진행 방향, 남은 예상 바닷길). 위치 신선도는 서버가 rules.md로 정한 값이다.
 * "펼쳐 보기"는 서버가 주는 값만 담고, 값이 있는 줄만 그린다(10-06): 호출부호, 선종, IMO, 선명 비슷한 정도, 목적지 코드, 칸별 출처·조회 시각, 결과 만든 시각.
 */
import {useEffect, useState} from 'react';
import {Anchor, LoaderCircle, Navigation, TriangleAlert} from 'lucide-react';
import {VesselMap} from './VesselMap';
import {getVesselDetail} from '@/lib/api';
import {countryLabel, dateTime, portLabel, shipTypeLabel, shown} from '@/lib/format';
import type {VesselDetailResponse, VesselItem} from '@/lib/types';

const SOURCE_LABEL: Record<string, string> = {mof: '해수부 입항 일정', shipfinder: '선박 위치', searoute: '남은 거리 계산'};
// 출처별 실패 안내. 서버 message에는 엔드포인트·키 이름·예외명이 섞여 있어 화면에 내지 않고 고정 문구만 쓴다 (10-02 화면 용어 점검)
const SOURCE_FAIL: Record<string, string> = {mof: '지금 받지 못했어요', shipfinder: '지금 받지 못했어요', searoute: '계산하지 못했어요'};

// 펼쳐 보기의 출처 표기. 모르는 이름은 서버가 준 글자 그대로 보인다
const SOURCE_NAME: Record<string, string> = {mof: '해수부', shipfinder: 'ShipFinder', searoute: '바닷길 계산'};
const from = (src?: string | null, at?: string | null) => src || at ? `${src ? SOURCE_NAME[src] ?? src : '출처 미상'}${at ? ` · ${dateTime(at)}` : ''}` : null;

/** 칸 하나: 이름은 연한 글씨, 값은 본문. 값이 없으면 "확인되지 않음"을 연하게 둔다 */
function Row({k, v, strong}: {k: string; v: string | null; strong?: boolean}) {
  return <div className={strong ? 'vd-row strong' : 'vd-row'}><dt>{k}</dt><dd className={v == null ? 'unknown' : undefined}>{shown(v)}</dd></div>;
}

export function VesselDetail({vessel}: {vessel: VesselItem}) {
  const [data, setData] = useState<VesselDetailResponse | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    setData(null); setError('');
    getVesselDetail(vessel.call_sign, vessel.ship_name)
      .then(d => { if (alive) setData(d); })
      .catch(e => { if (alive) setError(e instanceof Error ? e.message : '자세한 정보를 불러오지 못했어요.'); });
    return () => { alive = false; };
  }, [vessel.call_sign, vessel.ship_name]);

  const p = data?.position ?? null, s = data?.schedule ?? null, d = data?.distance ?? null, v = data?.vessel ?? null;
  const fresh = p ? (p.freshness === 'fresh' ? '정상 수신' : p.freshness === 'stale' ? '오래된 위치' : '수신 시각 확인 안 됨') : null;

  // 값이 있는 줄만 (없는 칸을 "확인되지 않음"으로 늘어놓지 않는다)
  const more = ([
    ['호출부호', v?.call_sign],
    ['선박 종류', v?.ship_type != null ? `${shipTypeLabel(v.ship_type)} (코드 ${v.ship_type})` : null],
    ['IMO 번호', v?.imo != null ? String(v.imo) : null],
    ['이름이 비슷한 정도', v?.similarity != null ? `${Math.round(v.similarity * 100)}% (내 화물의 배라는 뜻은 아니에요)` : null],
    ['목적지 코드', p?.destcode],
    ['선박 찾기 출처', from(v?.source, v?.cached_at ?? v?.fetched_at)],
    ['위치 출처', from(p?.source, p?.cached_at ?? p?.fetched_at)],
    ['거리 계산 출처', from(d?.source, d?.fetched_at)],
    ['입항 일정 출처', from(s?.source, s?.fetched_at)],
    ['이 결과를 만든 시각', data?.cached_at ? dateTime(data.cached_at) : null],
  ] as [string, string | null | undefined][]).filter((r): r is [string, string] => !!r[1]);

  return <article className="vessel-detail vd" aria-label={`${vessel.ship_name} 자세히 보기`}>
    <header className="vd-head">
      <div><h3>{vessel.ship_name}</h3><p>해수부 일정, 선박 위치, 부산까지 거리</p></div>
      {p && <span className={`fresh-chip ${p.freshness}`}><i aria-hidden="true"/>{fresh}</span>}
    </header>
    {error ? <p role="alert" className="request-error">{error}</p>
    : !data ? <div className="empty-inline"><LoaderCircle size={16} className="spin"/>해수부 일정과 선박 위치를 불러오는 중</div>
    : <>
      <div className="vessel-detail-grid vd-grid">
        <div className="vessel-detail-map">{p ? <VesselMap name={vessel.ship_name} lat={p.lat} lng={p.lng} sog={p.sog} cog={p.cog} freshness={p.freshness} lastTime={p.last_time} route={p.route ?? []} distanceNm={d?.distance_nm ?? null}/> : <div className="empty-state"><Navigation/><h3>선박 위치를 받지 못했어요.</h3></div>}</div>
        <div className="vessel-detail-info vd-info">
          <section><h4><Navigation size={16} strokeWidth={1.75}/>선박 위치(실시간)</h4>
            <dl>
              <Row k="선박 식별 번호와 국적" v={v ? `${v.mmsi} · ${countryLabel(v.flag)}` : null}/>
              <Row k="좌표" v={p ? `${p.lat.toFixed(2)}°N · ${p.lng.toFixed(2)}°E` : null}/>
              <Row k="속력과 진행 방향" v={p ? `${shown(p.sog)}노트 · ${shown(p.cog)}°` : null}/>
              <Row k="선박이 밝힌 목적지" v={p?.dest ? portLabel(p.dest) : null}/>
              <Row k="선박이 보낸 도착 예정" v={p?.ais_eta ? dateTime(p.ais_eta) : null}/>
              <Row k="마지막 수신" v={p?.last_time ? dateTime(p.last_time) : null}/>
            </dl>
          </section>
          <section><h4><Anchor size={16} strokeWidth={1.75}/>부산항 일정 (해수부)</h4>
            <dl>
              <Row k="입항 예정" v={s?.planned_arrival ? dateTime(s.planned_arrival) : null}/>
              <Row k="실제 입항" v={s?.actual_arrival ? dateTime(s.actual_arrival) : null}/>
              <Row k="접안 부두" v={s?.facility ?? vessel.facility}/>
              <Row strong k="부산까지" v={d ? `${d.distance_nm} 해리${d.calc_hours_at_sog != null ? ` · 지금 속력이면 약 ${d.calc_hours_at_sog.toFixed(1)}시간` : ''}` : null}/>
              <Row k="지금 속력 기준 예상 도착" v={d?.calc_eta ? dateTime(d.calc_eta) : null}/>
            </dl>
            {s && s.control_events.length > 0 && <ol className="control-events">{s.control_events.map((e, i) =>
              <li key={i}><strong>{e.kind}</strong><span>{dateTime(e.at)}</span><small>{shown(e.facility)}</small></li>)}</ol>}
          </section>
        </div>
      </div>
      {data.errors.length > 0 && <div className="info-note"><TriangleAlert size={16} strokeWidth={1.75}/><span>{data.errors.map(e => `${SOURCE_LABEL[e.source] ?? '일부 정보'}: ${SOURCE_FAIL[e.source] ?? '지금 받지 못했어요'}`).join(', ')}</span></div>}
      <p className="vd-caveat">예상 도착은 지금 속력을 끝까지 유지한다는 가정이에요. 화물 판정은 아니고, 내 화물은 B/L 번호로 조회해 주세요.</p>
      {more.length > 0 && <details className="vd-more"><summary><span className="vd-more-label">자세한 정보 펼쳐 보기<small>호출부호, 선박 종류, 출처, 조회 시각</small></span></summary>
        <dl>{more.map(([k, val]) => <Row key={k} k={k} v={val}/>)}</dl></details>}
    </>}
  </article>;
}
