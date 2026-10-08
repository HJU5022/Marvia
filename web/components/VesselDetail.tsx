'use client';
/** 입항 예정 선박 자세히 보기: 표에서 고른 줄 바로 아래에 펼쳐지는 내용 (docs/specs/chat-search.md "선박 자세히 보기").
 * 값은 GET /api/vessels/detail 한 번으로 오는 해수부 일정, AIS 위치, 부산까지 거리다. 받아 오는 일은 VesselList가 한다
 * (지도에 이전에 받은 배도 같이 남기려고 결과를 목록이 들고 있다). 이 파일은 받은 값을 그리기만 한다. 판정은 하지 않는다.
 * 지도는 이 안에 없다. 표 위의 큰 지도(VesselMap)가 고른 배로 날아간다.
 * 값 칸은 보통 글꼴이다. 한국어(확인되지 않음, 노트, 해리)가 고정폭 글꼴로 보이지 않게 한다 (UI 점검 V4).
 * "펼쳐 보기"에는 줄에 못 넣은 값(호출부호, 선박 종류, 다음에 들를 항구, 목적)과 출처·조회 시각, 출처 안내를 둔다.
 * 불러오는 동안은 큰 상자 대신 작은 뼈대 줄 세 개만 보인다.
 */
import {Anchor, Navigation, TriangleAlert} from 'lucide-react';
import {countryLabel, dateTime, portLabel, shipTypeLabel, shown} from '@/lib/format';
import type {VesselDetailResponse, VesselItem} from '@/lib/types';

/** 한 배의 자세히 받기 상태. 받은 시각(at)은 서버 10분 캐시와 같은 기준으로 다시 받을지 정할 때 쓴다 */
export type DetailEntry = {status: 'loading'} | {status: 'error'; message: string} | {status: 'done'; data: VesselDetailResponse; at: number};

const SOURCE_LABEL: Record<string, string> = {mof: '해수부 입항 일정', shipfinder: '선박 위치', searoute: '남은 거리 계산'};
// 출처별 실패 안내. 서버 message에는 엔드포인트·키 이름·예외명이 섞여 있어 화면에 내지 않고 고정 문구만 쓴다
const SOURCE_FAIL: Record<string, string> = {mof: '지금 받지 못했어요', shipfinder: '지금 받지 못했어요', searoute: '계산하지 못했어요'};

// 펼쳐 보기의 출처 표기. 모르는 이름은 서버가 준 글자 그대로 보인다
const SOURCE_NAME: Record<string, string> = {mof: '해수부', shipfinder: 'ShipFinder', searoute: '바닷길 계산'};
const from = (src?: string | null, at?: string | null) => src || at ? `${src ? SOURCE_NAME[src] ?? src : '출처 미상'}${at ? ` · ${dateTime(at)}` : ''}` : null;

/** 칸 하나: 이름은 연한 글씨, 값은 본문. 값이 없으면 "확인되지 않음"을 연하게 둔다 */
function Row({k, v}: {k: string; v: string | null}) {
  return <div className="vd-row"><dt>{k}</dt><dd className={v == null ? 'unknown' : undefined}>{shown(v)}</dd></div>;
}

export function VesselDetail({vessel, entry}: {vessel: VesselItem; entry: DetailEntry | undefined}) {
  const data = entry?.status === 'done' ? entry.data : null;
  const p = data?.position ?? null, s = data?.schedule ?? null, d = data?.distance ?? null, v = data?.vessel ?? null;
  const fresh = p ? (p.freshness === 'fresh' ? '정상 수신' : p.freshness === 'stale' ? '오래된 위치' : '수신 시각 확인 안 됨') : null;

  // 값이 있는 줄만 (없는 칸을 "확인되지 않음"으로 늘어놓지 않는다). 줄에 있던 값도 여기서 다시 볼 수 있다
  const more = ([
    ['호출부호', v?.call_sign ?? vessel.call_sign],
    ['선박 종류', v?.ship_type != null ? `${shipTypeLabel(v.ship_type)} (코드 ${v.ship_type})` : vessel.ship_kind],
    ['다음에 들를 항구', vessel.next_port],
    ['입항 목적', vessel.purpose],
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
    {/* 줄에 이미 선명이 있어 눈에는 안 보이게 두고, 화면 낭독기에는 어느 배의 내용인지 알린다 */}
    <header className="vd-head"><h3 className="sr-only">{vessel.ship_name}</h3></header>
    {!entry || entry.status === 'loading' ? <div className="vd-skel" role="status" aria-label="해수부 일정과 선박 위치를 불러오는 중이에요"><span className="skeleton"/><span className="skeleton"/><span className="skeleton"/></div>
    : entry.status === 'error' ? <p role="alert" className="request-error">{entry.message}</p>
    : <>
      <div className="vd-top">
        <div className="vd-fact"><span>부산까지</span>
          <b>{d ? `${d.distance_nm} 해리` : '확인되지 않음'}</b>
          {d?.calc_hours_at_sog != null && <small>지금 속력이면 약 {d.calc_hours_at_sog.toFixed(1)}시간</small>}
        </div>
        {p && <span className={`fresh-chip ${p.freshness}`}><i aria-hidden="true"/>{fresh}{p.last_time && <small>{dateTime(p.last_time, true)} 수신</small>}</span>}
      </div>
      <div className="vessel-detail-info vd-info">
        <section><h4><Anchor size={16} strokeWidth={1.75}/>부산항 일정 (해수부)</h4>
          <dl>
            <Row k="입항 예정" v={s?.planned_arrival ? dateTime(s.planned_arrival) : vessel.expected_arrival ? dateTime(vessel.expected_arrival) : null}/>
            <Row k="실제 입항" v={s?.actual_arrival ? dateTime(s.actual_arrival) : null}/>
            <Row k="접안 부두" v={s?.facility ?? vessel.facility}/>
            <Row k="지금 속력 기준 예상 도착" v={d?.calc_eta ? dateTime(d.calc_eta) : null}/>
          </dl>
          {s && s.control_events.length > 0 && <ol className="control-events">{s.control_events.map((e, i) =>
            <li key={i}><strong>{e.kind}</strong><span>{dateTime(e.at)}</span><small>{shown(e.facility)}</small></li>)}</ol>}
        </section>
        <section><h4><Navigation size={16} strokeWidth={1.75}/>선박 위치 (실시간)</h4>
          <dl>
            <Row k="선박 식별 번호와 국적" v={v ? `${v.mmsi} · ${countryLabel(v.flag)}` : null}/>
            <Row k="좌표" v={p ? `${p.lat.toFixed(2)}°N · ${p.lng.toFixed(2)}°E` : null}/>
            <Row k="속력과 진행 방향" v={p ? `${shown(p.sog)}노트 · ${shown(p.cog)}°` : null}/>
            <Row k="선박이 밝힌 목적지" v={p?.dest ? portLabel(p.dest) : null}/>
            <Row k="선박이 보낸 도착 예정" v={p?.ais_eta ? dateTime(p.ais_eta) : null}/>
          </dl>
        </section>
      </div>
      {data!.errors.length > 0 && <div className="info-note"><TriangleAlert size={16} strokeWidth={1.75}/><span>{data!.errors.map(e => `${SOURCE_LABEL[e.source] ?? '일부 정보'}: ${SOURCE_FAIL[e.source] ?? '지금 받지 못했어요'}`).join(', ')}</span></div>}
      <p className="vd-caveat">예상 도착은 지금 속력을 끝까지 유지한다는 가정이에요. 화물 판정은 아니고, 내 화물은 B/L 번호로 조회해 주세요.</p>
      <details className="vd-more"><summary><span className="vd-more-label">자세한 정보 펼쳐 보기<small>호출부호, 선박 종류, 출처, 조회 시각</small></span></summary>
        {more.length > 0 && <dl>{more.map(([k, val]) => <Row key={k} k={k} v={val}/>)}</dl>}
        <p className="vd-caveat">출처: 해양수산부 선박운항정보(입항 신고). 직전에 들른 항구 기준이고, 처음 출발한 항구와 시각은 신고에 없어요.</p>
      </details>
    </>}
  </article>;
}
