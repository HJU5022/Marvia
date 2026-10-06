'use client';
/** 감시·지도 (docs/specs/cargo-watch.md, 10-02). 내 화물 B/L마다 그 배의 마지막 위치를 한 지도에 서로 다른 마커로 보여 준다.
 * - 위치는 worker가 6시간마다 모은 마지막 값을 쓸 예정이다 (watch_positions, 017). 지금은 위치 수집이 꺼져 있어(ShipFinder 호출 한도) 예시 데이터다
 * - 반출이 끝난 화물(status done)은 지도에서 빼고 목록 아래에 개수만 알린다
 * - 마커에 마우스를 올리면 선명, 가린 B/L, 운송 화물 이름표, 판정, 통관 단계, 도착 예정, 위치 수신 시각이 뜬다.
 *   운송 화물은 사용자가 붙인 이름표만 쓴다. UNI-PASS 품명은 저장·표시하지 않는다 (SDD 3.5)
 * - 배마다 6시간 간격 위치 이력(track)을 그 배 색의 선으로 잇고, 찍힌 지점마다 작은 동그라미를 단다. 마우스를 올리면 시각과 속력
 * - 배끼리 화면에서 가까우면(CLUSTER_PX 안) 숫자 클러스터로 묶는다. 확대 단계가 바뀔 때마다 다시 묶는다.
 *   클러스터를 누르면 상세 창에 그 안의 배와 말풍선 내용 전부가 뜬다. 새 라이브러리(leaflet.markercluster) 없이 직접 묶는다
 * 판정은 하지 않는다. 표시만 한다. */
import {useEffect, useRef, useState} from 'react';
import {LocateFixed, Maximize2, Radar, X} from 'lucide-react';
import type {GeoJsonObject} from 'geojson';
import {getGeography, getPresentationData, getWatchList, type WatchItem, type WatchList} from '@/lib/api';
import {dateTime, verdictLabels} from '@/lib/format';
import {VerdictBadge} from '@/components/Shared';

// 화물마다 다른 마커 색. 판정 색(초록·노랑·빨강)과 겹치지 않게 고른다. 색이 모자라면 처음부터 다시 쓰고 글자로 구분한다
const PALETTE = ['#1d4ed8', '#7c3aed', '#0f766e', '#c2410c', '#be185d', '#4d7c0f', '#0369a1', '#a21caf', '#b45309', '#334155'];
const markerLetter = (i: number) => String.fromCharCode(65 + (i % 26));
const colorOf = (i: number) => PALETTE[i % PALETTE.length];
// 화면에서 이 거리(px) 안에 있는 배끼리 한 클러스터로 묶는다. 핀 폭(34px)보다 조금 넓게
const CLUSTER_PX = 44;
/** 위치가 있어 지도에 올릴 수 있는 화물 */
type Located = WatchItem & {lat: number; lng: number};

/** 말풍선과 클러스터 상세 창이 같이 쓰는 항목 */
function rowsOf(item: WatchItem): [string, string][] {
  return [
    ['B/L', item.bl_masked],
    ['운송 화물', item.label ?? item.goods_name ?? '이름표 없음'],  // 이름표가 없으면 UNI-PASS 품명 (10-06)
    ['판정', item.verdict ? verdictLabels[item.verdict] : '판정 없음'],
    ['통관 단계', item.stage ?? '확인되지 않음'],
    ['도착 예정', item.eta ? dateTime(item.eta, true) : '확인되지 않음'],
    ['위치 수신', dateTime(item.position_at, true)],
  ];
}
function motion(item: WatchItem) {
  return item.sog != null ? `${item.sog}노트${item.cog != null ? ` · ${Math.round(item.cog)}°` : ''}` : null;
}
/** Leaflet 말풍선은 React가 아니라 글자를 직접 이스케이프한다 */
function esc(v: string) { return v.replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c] as string)); }
function tip(item: WatchItem, letter: string) {
  const move = motion(item);
  return `<div class="watch-tip"><strong>${esc(letter)} · ${esc(item.ship_name)}</strong>${move ? `<span>${esc(move)}</span>` : ''}`
    + `<dl>${rowsOf(item).map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl></div>`;
}

export function WatchMap() {
  const [list, setList] = useState<WatchList | null>(null);
  const [showTrack, setShowTrack] = useState(true);  // 경로 보기 켜고 끄기
  const [cluster, setCluster] = useState<number[] | null>(null);  // 누른 클러스터 안의 배 번호들. 상세 창에 보인다
  const [selected, setSelected] = useState<number | null>(null);  // 지금 고른 배. 목록 카드를 강조한다 (보기 전용 상태)
  const host = useRef<HTMLDivElement>(null);
  const focus = useRef<(i: number) => void>(() => {});
  const fitAll = useRef<() => void>(() => {});
  useEffect(() => { let alive = true; void getWatchList().then(l => { if (alive) setList(l); }); return () => { alive = false; }; }, []);

  // 지도에는 위치가 있는 화물만 올린다. 위치 수집 전 화물은 아래 줄에 이름만 보여 준다 (GET /api/watch, 10-06)
  const active = list?.items.filter((i): i is Located => i.status === 'active' && i.lat != null && i.lng != null) ?? [];
  const waiting = list?.items.filter(i => i.status === 'active' && (i.lat == null || i.lng == null)) ?? [];
  const done = list?.items.filter(i => i.status === 'done').length ?? 0;

  useEffect(() => {
    if (!active.length) return;
    let disposed = false;
    setSelected(null);
    let cleanup: (() => void) | undefined;
    void import('leaflet').then(L => {
      if (disposed || !host.current) return;
      const {demo} = getPresentationData();
      const css = getComputedStyle(document.documentElement);
      const color = (n: string) => css.getPropertyValue(n).trim();
      const map = L.map(host.current, {zoomControl: true, scrollWheelZoom: true, minZoom: 4, maxZoom: 10});
      const points = active.flatMap(i => [L.latLng(i.lat, i.lng), ...(showTrack ? (i.track ?? []).map(t => L.latLng(t.lat, t.lng)) : [])]);
      const port = L.latLng(demo.port.lat, demo.port.lng);
      // 중심을 먼저 정한 뒤 선을 올린다 (VesselMap과 같은 이유: 범위를 모르면 Leaflet이 멈춘다)
      map.fitBounds(L.latLngBounds([...points, port]).pad(.25), {maxZoom: 8, animate: false});
      L.geoJSON(getGeography() as GeoJsonObject, {style: {color: color('--coast'), weight: 1, fillColor: color('--land'), fillOpacity: 1}, interactive: false}).addTo(map);
      map.attributionControl.setPrefix(false).addAttribution('Leaflet · Natural Earth (public domain)');
      // 부산항 마커는 배 핀보다 아래층에 두고, 이름표(툴팁 층)는 늘 핀 위에 떠서 배가 같은 자리에 있어도 가려지지 않는다
      L.marker(port, {icon: L.divIcon({className: 'port-marker', html: '<span>⚑</span>', iconSize: [28, 28], iconAnchor: [14, 14]}), interactive: false, zIndexOffset: -1000})
        .addTo(map).bindTooltip('부산항', {permanent: true, direction: 'bottom', offset: [0, 12], className: 'port-tooltip'});

      // 경로 동그라미는 배 핀·클러스터보다 아래 층에 둔다. 같은 층이면 위도 순으로 겹쳐 클러스터를 가려 누를 수 없었다 (10-02 확인)
      map.createPane('watch-track').style.zIndex = '550';  // overlay(선) 400 < 경로 점 550 < 마커 600
      // 경로: 지난 위치를 오래된 순으로 선으로 잇고, 현재 위치를 뺀 지점마다 작은 동그라미 (마지막 점은 큰 핀).
      // 평소에는 모든 배 경로를 흐리게 깔고, 고른 배(핀·목록·클러스터 상세에서 누름)의 경로만 진하게 보인다 (10-02 사용자 결정).
      // 경로 점에는 말풍선을 달지 않는다
      const trackLines: (L.Polyline | null)[] = [];
      const trackDots: L.Marker[][] = [];
      active.forEach((item, i) => {
        const track = showTrack ? (item.track ?? []) : [];
        if (track.length < 2) { trackLines.push(null); trackDots.push([]); return; }
        const c = colorOf(i);
        trackLines.push(L.polyline(track.map(t => [t.lat, t.lng] as L.LatLngTuple), {color: c, weight: 3, opacity: .25, interactive: false}).addTo(map));
        trackDots.push(track.slice(0, -1).map(t =>
          L.marker([t.lat, t.lng], {icon: L.divIcon({className: 'track-dot faint', html: `<span style="--pin:${c}"></span>`, iconSize: [12, 12], iconAnchor: [6, 6]}),
            keyboard: false, interactive: false, pane: 'watch-track'}).addTo(map)));
      });
      // i가 null이면 전부 흐리게. 고른 배는 선을 굵고 진하게, 점을 또렷하게
      const highlight = (sel: number | null) => {
        setSelected(sel);
        trackLines.forEach((line, i) => line?.setStyle(i === sel ? {opacity: .95, weight: 4} : {opacity: .25, weight: 3}));
        trackDots.forEach((dots, i) => dots.forEach(d => d.getElement()?.classList.toggle('faint', i !== sel)));
        if (sel !== null) trackLines[sel]?.bringToFront();
      };

      // 배 핀은 지도에 바로 올리지 않고 묶음 레이어에 둔다. 확대 단계마다 가까운 배끼리 클러스터로 다시 묶는다
      const markers = active.map((item, i) => {
        const letter = markerLetter(i);
        const icon = L.divIcon({className: 'watch-pin', iconSize: [34, 42], iconAnchor: [17, 40],
          html: `<span style="--pin:${colorOf(i)}" class="pin-body ${item.verdict ?? ''}"><b>${letter}</b></span>`});
        return L.marker([item.lat, item.lng], {icon, title: `${letter} ${item.ship_name}`, alt: `${letter} ${item.ship_name}`, riseOnHover: true})
          .bindTooltip(tip(item, letter), {direction: 'top', offset: [0, -36], className: 'watch-tooltip', opacity: 1})
          .on('click', e => { L.DomEvent.stopPropagation(e); highlight(i); });
      });
      const layer = L.layerGroup().addTo(map);

      // 목록에서 연 말풍선은 마우스를 떼도 저절로 안 닫힌다. 한 번에 하나만 열어 두고,
      // 다른 배를 고르거나, 다른 마커에 마우스를 올리거나, 지도 빈 곳을 누르면 닫는다 (10-02 사용자 발견: 말풍선이 쌓였다)
      let opened: L.Marker | null = null;
      const closeOpened = () => { opened?.closeTooltip(); opened = null; };
      markers.forEach(m => m.on('mouseover', () => { if (opened && opened !== m) closeOpened(); }));
      map.on('click', () => { closeOpened(); setCluster(null); highlight(null); });

      let groups: number[][] = [];
      const recluster = () => {
        closeOpened();
        layer.clearLayers();
        const pts = active.map(it => map.latLngToLayerPoint([it.lat, it.lng]));
        const used = new Set<number>();
        groups = [];
        active.forEach((_, i) => {
          if (used.has(i)) return;
          const g = [i]; used.add(i);
          active.forEach((__, j) => { if (!used.has(j) && pts[i].distanceTo(pts[j]) < CLUSTER_PX) { g.push(j); used.add(j); } });
          groups.push(g);
        });
        groups.forEach(g => {
          if (g.length === 1) { layer.addLayer(markers[g[0]]); return; }
          const center = L.latLng(g.reduce((a, k) => a + active[k].lat, 0) / g.length, g.reduce((a, k) => a + active[k].lng, 0) / g.length);
          // 테두리는 안에서 가장 급한 판정 색. 아래 점은 안에 든 배들의 색(최대 4개)
          const urgent = g.some(k => active[k].verdict === 'act') ? 'act' : g.some(k => active[k].verdict === 'watch') ? 'watch' : '';
          const dots = g.slice(0, 4).map(k => `<em style="background:${colorOf(k)}"></em>`).join('');
          const names = g.map(k => `${markerLetter(k)} ${active[k].ship_name}`).join(', ');
          L.marker(center, {icon: L.divIcon({className: 'watch-cluster', iconSize: [46, 46], iconAnchor: [23, 23],
            html: `<span class="cluster-body ${urgent}"><b>${g.length}</b><i>${dots}</i></span>`}), title: `배 ${g.length}척: ${names}`, alt: `배 ${g.length}척`, riseOnHover: true, zIndexOffset: 1000})
            .on('click', e => { L.DomEvent.stopPropagation(e); closeOpened(); setCluster(g); })
            .bindTooltip(`<div class="watch-tip"><strong>배 ${g.length}척</strong><span>${esc(names)}</span><span>눌러서 자세히 보기</span></div>`, {direction: 'top', offset: [0, -22], className: 'watch-tooltip', opacity: 1})
            .addTo(layer);
        });
      };
      map.on('zoomend', recluster);
      recluster();

      // 목록·상세 창에서 배를 고르면 그 배의 경로 전체(경로가 없으면 현재 위치)로 확대한다.
      // 확대한 뒤에도 다른 배와 묶여 있으면 그 클러스터의 상세 창을, 혼자면 그 배 말풍선을 연다
      focus.current = i => {
        closeOpened(); setCluster(null); highlight(i);
        let finished = false;
        const after = () => {
          if (finished) return; finished = true;
          const g = groups.find(x => x.includes(i));
          // 최대로 확대해도 붙어 있는 배(같은 부두 등)는 상세 창으로 보이되, 누른 배를 맨 위에 둔다
          if (g && g.length > 1) setCluster([i, ...g.filter(x => x !== i)]);
          else { markers[i].openTooltip(); opened = markers[i]; }
        };
        map.once('moveend', after);
        setTimeout(after, 700);  // 이미 그 자리라 지도가 안 움직이면 moveend가 오지 않는다
        // 그 배가 다른 배와 떨어져 보이는(클러스터에서 빠지는) 가장 낮은 확대 단계를 찾는다.
        // 경로 전체가 들어오는 단계가 그보다 낮으면 경로를 포기하고 배를 가운데 두고 그 단계로 확대한다 (10-02 사용자 발견:
        // 클러스터 안의 배를 목록에서 누르면 경로 범위에만 맞춰져 그 배로 가지 않았다)
        const here = L.latLng(active[i].lat, active[i].lng);
        const apartAt = (z: number) => active.every((o, j) => j === i
          || map.project(here, z).distanceTo(map.project(L.latLng(o.lat, o.lng), z)) >= CLUSTER_PX);
        let apart = map.getMaxZoom();
        for (let z = map.getMinZoom(); z <= map.getMaxZoom(); z++) { if (apartAt(z)) { apart = z; break; } }
        const track = showTrack ? (active[i].track ?? []) : [];
        const trackBounds = track.length > 1 ? L.latLngBounds(track.map(t => L.latLng(t.lat, t.lng))).pad(.3) : null;
        const trackZoom = trackBounds ? Math.min(map.getBoundsZoom(trackBounds), 9) : 0;
        if (trackBounds && trackZoom >= apart) map.fitBounds(trackBounds, {maxZoom: 9, animate: true});
        else map.setView(here, Math.max(apart, 8), {animate: true});
      };
      fitAll.current = () => { setCluster(null); map.fitBounds(L.latLngBounds([...points, port]).pad(.25), {maxZoom: 8, animate: true}); };

      const ro = new ResizeObserver(() => map.invalidateSize());
      ro.observe(host.current);
      cleanup = () => { ro.disconnect(); map.remove(); };
    });
    return () => { disposed = true; cleanup?.(); };
  }, [list, showTrack]);  // eslint-disable-line react-hooks/exhaustive-deps

  return <section className="watch" aria-labelledby="watch-title">
    <div className="watch-head">
      <div><h2 id="watch-title"><Radar size={20}/>감시·지도</h2>
        <p>내 화물의 배가 지금 어디쯤 있는지 한눈에 봅니다. 위치는 6시간마다 갱신됩니다.</p></div>
      <div className="watch-head-side">
        {list?.sample && <span className="subtle-badge" role="note">예시 데이터</span>}
        {list?.updated_at && <span className="watch-updated">{dateTime(list.updated_at, true)} 기준</span>}
      </div>
    </div>
    {!list ? <div className="watch-empty">감시 화물을 불러오는 중입니다.</div>
      : !active.length && !waiting.length ? <div className="watch-empty">감시 중인 화물이 없습니다. B/L을 조회하면 이곳에 자동으로 추가됩니다.</div>
      : !active.length ? null
      : <div className="watch-body">
        <div className="watch-map-col">
          <div className="watch-toolbar">
            <button type="button" className="watch-fit" onClick={() => fitAll.current()} title="모든 배 보기" aria-label="모든 배 보기"><Maximize2 size={16}/>모든 배 보기</button>
            <label className="watch-track-toggle"><input type="checkbox" checked={showTrack} onChange={e => setShowTrack(e.target.checked)}/>경로 보기 (6시간 간격)</label>
          </div>
          <div className="watch-map">
            <div ref={host} className="leaflet-host"/>
            {cluster && <div className="cluster-panel" role="dialog" aria-label={`이 자리의 배 ${cluster.length}척`} onKeyDown={e => { if (e.key === 'Escape') setCluster(null); }}>
              <div className="cluster-head"><strong>이 자리의 배 {cluster.length}척</strong>
                <button type="button" className="icon-button" onClick={() => setCluster(null)} aria-label="닫기" autoFocus><X size={16}/></button></div>
              <ul>{cluster.map(k => { const item = active[k]; const move = motion(item); return <li key={item.bl_masked}>
                <div className="cluster-item-head"><span className="watch-chip" style={{background: colorOf(k)}}>{markerLetter(k)}</span>
                  <span className="watch-main"><strong>{item.ship_name}</strong>{move && <small>{move}</small>}</span>
                  <button type="button" className="cluster-go" onClick={() => focus.current(k)} aria-label={`${item.ship_name}로 이동`}><LocateFixed size={16}/>이 배로</button></div>
                <dl>{rowsOf(item).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
              </li>; })}</ul>
            </div>}
          </div>
        </div>
        <ol className="watch-list" aria-label="감시 중인 화물">
          {active.map((item, i) => <li key={item.bl_masked}>
            <button type="button" className={selected === i ? 'selected' : ''} aria-pressed={selected === i} onClick={() => focus.current(i)} aria-label={`${markerLetter(i)} ${item.ship_name} 지도에서 보기`}>
              <span className="watch-chip" style={{background: colorOf(i)}}>{markerLetter(i)}</span>
              <span className="watch-main">
                <strong className="watch-goods">{item.label ?? item.goods_name ?? '이름표 없음'}</strong>
                <span className="watch-ship">{item.ship_name}{item.ship_flag ? ` · ${item.ship_flag}` : ''}</span>
                <small className="watch-bl">{item.bl_masked}</small>
                <span className="watch-stage">통관 {item.stage ?? '확인되지 않음'}</span>
              </span>
              <VerdictBadge verdict={item.verdict}/>
            </button>
          </li>)}
        </ol>
      </div>}
    {waiting.length > 0 && <p className="watch-done">위치 수집 전: {waiting.map(i => `${i.ship_name}${i.goods_name ? ` (${i.goods_name})` : ''}`).join(', ')}. 다음 조회나 위치 수집 뒤 지도에 나옵니다.</p>}
    {done > 0 && <p className="watch-done">반출이 끝난 화물 {done}건은 지도에서 뺐습니다.</p>}
  </section>;
}
