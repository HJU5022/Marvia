'use client';
/** 지켜보는 화물 (docs/specs/cargo-watch.md). 내 화물 B/L마다 그 배의 마지막 위치를 한 지도에 서로 다른 마커로 보여 준다.
 * - 위치는 worker가 6시간마다 모은 마지막 값을 쓸 예정이다 (watch_positions, 017). 지금은 위치 수집이 꺼져 있어(ShipFinder 호출 한도) 예시 데이터다
 * - 반출이 끝난 화물(status done)은 지도에서 빼고 목록 아래에 개수만 알린다
 * - 마커에 마우스를 올리면 선명, 가린 B/L, 운송 화물 이름표, 판정, 통관 단계, 도착 예정, 위치 수신 시각이 뜬다.
 *   운송 화물은 사용자가 붙인 이름표만 쓴다. UNI-PASS 품명은 저장·표시하지 않는다 (SDD 3.5)
 * - 배마다 6시간 간격 위치 이력(track)을 그 배 색의 선으로 잇고, 찍힌 지점마다 작은 동그라미를 단다. 마우스를 올리면 시각과 속력
 * - 배끼리 화면에서 가까우면(CLUSTER_PX 안) 숫자 클러스터로 묶는다. 확대 단계가 바뀔 때마다 다시 묶는다.
 *   클러스터를 누르면 상세 창에 그 안의 배와 말풍선 내용 전부가 뜬다. 새 라이브러리(leaflet.markercluster) 없이 직접 묶는다
 * 판정은 하지 않는다. 표시만 한다. */
import {useEffect, useRef, useState, type CSSProperties} from 'react';
import {LocateFixed, Maximize2, X} from 'lucide-react';
import {addBasemap, drawLocalGeography} from '@/lib/basemap';
import {getPresentationData, getWatchList, type WatchItem, type WatchList} from '@/lib/api';
import {dateTime, timeOrRaw, verdictLabels} from '@/lib/format';
import {listWatchedVessels, onVesselWatchChange, vesselWatchEnabled, type WatchedVessel} from '@/lib/watchVessel';
import {VerdictBadge} from '@/components/Shared';

// 화물마다 다른 마커 색. 판정 색(초록·노랑·빨강)과 겹치지 않게 고른다. 색이 모자라면 처음부터 다시 쓰고 글자로 구분한다
const PALETTE = ['#1d4ed8', '#7c3aed', '#0f766e', '#c2410c', '#be185d', '#4d7c0f', '#0369a1', '#a21caf', '#b45309', '#334155'];
const markerLetter = (i: number) => String.fromCharCode(65 + (i % 26));
const colorOf = (i: number) => PALETTE[i % PALETTE.length];
// 배만 지켜보는 배(판정 없음)의 점 색. 화물 색·판정 색과 겹치지 않는 회색 (클러스터 아래 점에 쓴다)
const VESSEL_ONLY_COLOR = '#9ca3af';
// 화면에서 이 거리(px) 안에 있는 배끼리 한 클러스터로 묶는다. 핀 폭(34px)보다 조금 넓게
const CLUSTER_PX = 44;
/** 위치가 있어 지도에 올릴 수 있는 화물 */
type Located = WatchItem & {lat: number; lng: number};

/** 지도에 올리는 점 하나. B/L 화물(cargo)이거나 배만 지켜보는 배(vessel)다. 둘은 같은 핀 모양·같은 클러스터를 쓴다 */
type Spot = {lat: number; lng: number; cargo?: Located; vessel?: WatchedVessel};

/** 진짜 선명만. 서버가 선명을 모르면 api.ts가 가린 B/L로 채워 오므로(ship_name ?? bl_masked) 같은 값이면 선명이 아니다 */
const realShip = (item: WatchItem) => item.ship_name && item.ship_name !== item.bl_masked ? item.ship_name : null;
/** 화물 이름: 이름표 > 품명 > 진짜 선명 > "B/L 가린번호" 한 번 */
const nameOf = (item: WatchItem) => item.label ?? item.goods_name ?? realShip(item) ?? `B/L ${item.bl_masked}`;
/** 지도 핀·말풍선·목록 둘째 줄에 쓰는 배 표시. 선명이 없으면 화물 이름으로 대신한다 */
const shipOf = (item: WatchItem) => realShip(item) ?? nameOf(item);

/** 말풍선과 클러스터 상세 창이 같이 쓰는 항목 */
function rowsOf(item: WatchItem): [string, string][] {
  return [
    ['화물 이름', nameOf(item)],  // 이름표가 없으면 UNI-PASS 품명
    ['B/L', item.bl_masked],
    ['국적', item.ship_flag ?? '-'],  // 시안에 국적 칸이 있다. 값이 없으면 대시
    ['통관 단계', item.stage ?? '확인 안 됨'],
    ['도착 예정', item.eta ? dateTime(item.eta, true) : '확인 안 됨'],
    ['위치 받은 시각', dateTime(item.position_at, true)],
  ];
}
function motion(item: WatchItem) {
  return item.sog != null ? `${item.sog}노트${item.cog != null ? ` · ${Math.round(item.cog)}°` : ''}` : null;
}
/** Leaflet 말풍선은 React가 아니라 글자를 직접 이스케이프한다 */
function esc(v: string) { return v.replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c] as string)); }
function tip(item: WatchItem, letter: string) {
  const move = motion(item);
  // 시안: 말풍선 머리에 배 이름과 판정 배지. 판정이 없으면 배지를 그리지 않는다
  const badge = item.verdict ? `<span class="verdict-badge ${item.verdict}">${esc(verdictLabels[item.verdict])}</span>` : '';
  return `<div class="watch-tip"><header><strong>${esc(letter)} · ${esc(shipOf(item))}</strong>${badge}</header>${move ? `<span>${esc(move)}</span>` : ''}`
    + `<dl>${rowsOf(item).map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl></div>`;
}

export function WatchMap() {
  const [list, setList] = useState<WatchList | null>(null);
  const [showTrack, setShowTrack] = useState(true);  // 경로 보기 켜고 끄기
  const [cluster, setCluster] = useState<number[] | null>(null);  // 누른 클러스터 안의 배 번호들. 상세 창에 보인다
  const [selected, setSelected] = useState<number | null>(null);  // 지금 고른 배. 목록 카드를 강조한다 (보기 전용 상태)
  const [hovered, setHovered] = useState<number | null>(null);  // 마우스·키보드가 가리키는 배. 선택과 별개인 임시 강조 (지도 ↔ 목록 양방향)
  // B/L 없이 배만 지켜보는 배도 같은 지도에 따로 찍는다. null은 아직 읽는 중
  const [vessels, setVessels] = useState<WatchedVessel[] | null>(vesselWatchEnabled ? null : []);
  const host = useRef<HTMLDivElement>(null);
  const listEl = useRef<HTMLOListElement>(null);
  const hover = useRef<(i: number | null, fromMap?: boolean) => void>(() => {});
  const focus = useRef<(i: number) => void>(() => {});
  const fitAll = useRef<() => void>(() => {});
  useEffect(() => {
    if (!vesselWatchEnabled) return;
    let alive = true;
    const load = () => listWatchedVessels().then(l => { if (alive) setVessels(l); }).catch(() => { if (alive) setVessels(v => v ?? []); });
    void load();
    const off = onVesselWatchChange(() => void load());
    return () => { alive = false; off(); };
  }, []);
  useEffect(() => { let alive = true; void getWatchList().then(l => { if (alive) setList(l); }); return () => { alive = false; }; }, []);

  // 지도에는 위치가 있는 화물만 올린다. 위치 수집 전 화물은 아래 줄에 이름만 보여 준다 (GET /api/watch)
  const active = list?.items.filter((i): i is Located => i.status === 'active' && i.lat != null && i.lng != null) ?? [];
  const waiting = list?.items.filter(i => i.status === 'active' && (i.lat == null || i.lng == null)) ?? [];
  const done = list?.items.filter(i => i.status === 'done').length ?? 0;
  const total = active.length + waiting.length;
  // 위치가 있는 배만 지도에 찍는다. 위치 없는 배는 아래 "지켜보는 배" 목록에 글로 나온다
  // 같은 배(MMSI)가 두 번 오면 마커가 겹쳐 글상자가 두 겹으로 보였다. MMSI마다 가장 늦게 받은 위치 하나만 남긴다.
  // 화물(B/L) 쪽 항목에는 MMSI가 없어, 화물의 진짜 선명이 같은 배는 화물 마커 하나만 보이도록 이름(대소문자·공백 무시)으로 뺀다
  const normName = (n: string) => n.trim().toUpperCase().replace(/\s+/g, ' ');
  const cargoShips = new Set(active.map(i => realShip(i)).filter((n): n is string => !!n).map(normName));
  const latestByMmsi = new Map<number, WatchedVessel>();
  (vessels ?? []).filter(v => v.lat != null && v.lng != null).forEach(v => {
    const prev = latestByMmsi.get(v.mmsi);
    if (!prev || (v.position_at ?? '') > (prev.position_at ?? '')) latestByMmsi.set(v.mmsi, v);
  });
  const vesselPins = [...latestByMmsi.values()].filter(v => !cargoShips.has(normName(v.name)));
  // 클러스터·확대·상세 창이 같이 쓰는 점 목록. 번호 0..active.length-1은 화물(목록·경로 번호와 같다), 그 뒤는 배만 지켜보는 배
  const spots: Spot[] = [...active.map(c => ({lat: c.lat, lng: c.lng, cargo: c})), ...vesselPins.map(v => ({lat: v.lat as number, lng: v.lng as number, vessel: v}))];
  const spotName = (sp: Spot) => sp.cargo ? shipOf(sp.cargo) : sp.vessel?.name ?? '';
  const spotColor = (k: number) => spots[k]?.vessel ? VESSEL_ONLY_COLOR : colorOf(k);

  useEffect(() => {
    if (!list || !(total || vesselPins.length)) return;  // 위치 있는 화물이 없어도 부산항 기준 빈 지도는 그린다
    let disposed = false;
    setSelected(null);
    let cleanup: (() => void) | undefined;
    void import('leaflet').then(L => {
      if (disposed || !host.current) return;
      const {demo} = getPresentationData();
      const css = getComputedStyle(document.documentElement);
      const color = (n: string) => css.getPropertyValue(n).trim();
      const map = L.map(host.current, {zoomControl: true, scrollWheelZoom: true, minZoom: 4, maxZoom: 10});
      const points = [...active.flatMap(i => [L.latLng(i.lat, i.lng), ...(showTrack ? (i.track ?? []).map(t => L.latLng(t.lat, t.lng)) : [])]),
        ...vesselPins.map(v => L.latLng(v.lat as number, v.lng as number))];
      const port = L.latLng(demo.port.lat, demo.port.lng);
      // 중심을 먼저 정한 뒤 선을 올린다 (VesselMap과 같은 이유: 범위를 모르면 Leaflet이 멈춘다)
      if (points.length) map.fitBounds(L.latLngBounds([...points, port]).pad(.25), {maxZoom: 8, animate: false});
      else map.setView(port, 6, {animate: false});
      // 바탕은 세계 지도, 못 쓰면 해안선 (lib/basemap.ts)
      const base = addBasemap(L, map, () => { drawLocalGeography(L, map); });
      map.attributionControl.setPrefix(false);
      // 부산항 마커는 배 핀보다 아래층에 두고, 이름표(툴팁 층)는 늘 핀 위에 떠서 배가 같은 자리에 있어도 가려지지 않는다
      L.marker(port, {icon: L.divIcon({className: 'port-marker', html: '<span>⚑</span>', iconSize: [28, 28], iconAnchor: [14, 14]}), interactive: false, zIndexOffset: -1000})
        .addTo(map).bindTooltip('부산항', {permanent: true, direction: 'bottom', offset: [0, 12], className: 'port-tooltip'});

      // 경로 동그라미는 배 핀·클러스터보다 아래 층에 둔다. 같은 층이면 위도 순으로 겹쳐 클러스터를 가려 누를 수 없었다
      map.createPane('watch-track').style.zIndex = '550';  // overlay(선) 400 < 경로 점 550 < 마커 600
      // 경로: 지난 위치를 오래된 순으로 선으로 잇고, 현재 위치를 뺀 지점마다 작은 동그라미 (마지막 점은 큰 핀).
      // 평소에는 모든 배 경로를 흐리게 깔고, 고른 배(핀·목록·클러스터 상세에서 누름)의 경로만 진하게 보인다.
      // 경로 점에는 말풍선을 달지 않는다
      const trackLines: (L.Polyline | null)[] = [];
      const trackHits: (L.Polyline | null)[] = [];  // 보이지 않는 굵은 선. 가는 선에 마우스를 맞추기 쉽게 한다
      const trackDots: L.Marker[][] = [];
      let selNow: number | null = null;  // 지금 고른 배 (state와 같은 값, 지도 쪽에서 바로 쓴다)
      let hovNow: number | null = null;  // 지금 가리키는 배
      active.forEach((item, i) => {
        const track = showTrack ? (item.track ?? []) : [];
        if (track.length < 2) { trackLines.push(null); trackHits.push(null); trackDots.push([]); return; }
        const c = colorOf(i);
        const pts = track.map(t => [t.lat, t.lng] as L.LatLngTuple);
        trackLines.push(L.polyline(pts, {color: c, weight: 3, opacity: .25, interactive: false}).addTo(map));
        const hit = L.polyline(pts, {color: c, weight: 16, opacity: 0, className: 'track-hit'}).addTo(map);
        hit.on('mouseover', () => hover.current(i, true)).on('mouseout', () => hover.current(null, true))
          .on('click', e => { L.DomEvent.stopPropagation(e); highlight(i); });
        trackHits.push(hit);
        trackDots.push(track.slice(0, -1).map(t =>
          L.marker([t.lat, t.lng], {icon: L.divIcon({className: 'track-dot faint', html: `<span style="--pin:${c}"></span>`, iconSize: [12, 12], iconAnchor: [6, 6]}),
            keyboard: false, interactive: true, pane: 'watch-track'}).addTo(map)
            .on('mouseover', () => hover.current(i, true)).on('mouseout', () => hover.current(null, true))
            .on('click', e => { L.DomEvent.stopPropagation(e); highlight(i); })));
      });
      // 선·점·핀의 모양을 고른 배(진하게)와 가리키는 배(중간)에 맞춰 다시 칠한다. 선택은 바꾸지 않는다
      const paint = () => {
        trackLines.forEach((line, i) => line?.setStyle(i === selNow ? {opacity: .95, weight: 4} : i === hovNow ? {opacity: .8, weight: 4} : {opacity: .25, weight: 3}));
        trackDots.forEach((dots, i) => dots.forEach(d => d.getElement()?.classList.toggle('faint', i !== selNow && i !== hovNow)));
        markers.forEach((m, i) => m.getElement()?.classList.toggle('hovered', i === hovNow));
        if (selNow !== null) trackLines[selNow]?.bringToFront();
        else if (hovNow !== null) trackLines[hovNow]?.bringToFront();
      };
      // i가 null이면 전부 흐리게. 고른 배는 선을 굵고 진하게, 점을 또렷하게
      const highlight = (sel: number | null) => { selNow = sel; setSelected(sel); paint(); };
      // 지도에서 가리키면(fromMap) 옆 목록이 그 줄로 스크롤하고, 목록에서 가리키면 지도 선·핀이 강조된다
      hover.current = (i, fromMap) => {
        hovNow = i; setHovered(i); paint();
        const row = i !== null && i < active.length && fromMap ? listEl.current?.children[i] as HTMLElement | undefined : undefined;
        const box = listEl.current;
        if (row && box && box.scrollHeight > box.clientHeight + 1) {
          const r = row.getBoundingClientRect(), b = box.getBoundingClientRect();
          if (r.top < b.top || r.bottom > b.bottom) {
            const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            box.scrollTo({top: box.scrollTop + (r.top < b.top ? r.top - b.top - 8 : r.bottom - b.bottom + 8), behavior: calm ? 'auto' : 'smooth'});
          }
        }
      };

      // 배 핀은 지도에 바로 올리지 않고 묶음 레이어에 둔다. 확대 단계마다 가까운 배끼리 클러스터로 다시 묶는다
      const markers = active.map((item, i) => {
        const letter = markerLetter(i);
        const icon = L.divIcon({className: 'watch-pin', iconSize: [34, 34], iconAnchor: [17, 17],
          html: `<span style="--pin:${colorOf(i)}" class="pin-body ${item.verdict ?? ''}"><b>${letter}</b></span>`});
        return L.marker([item.lat, item.lng], {icon, title: `${letter} ${shipOf(item)}`, alt: `${letter} ${shipOf(item)}`, riseOnHover: true})
          .bindTooltip(tip(item, letter), {direction: 'auto', offset: [18, 0], className: 'watch-tooltip', opacity: 1})
          .on('click', e => { L.DomEvent.stopPropagation(e); highlight(i); })
          .on('mouseover', () => hover.current(i, true)).on('mouseout', () => hover.current(null, true));
      });
      // 배만 지켜보는 배도 화물 핀과 같은 동그라미 핀·알파벳(화물 다음 글자부터)으로 그리고 같은 클러스터에 넣는다.
      // 전에는 방향 화살표로 따로 올려 클러스터에 안 묶이고 화물 핀과 포개졌다. 판정이 없다는 것은 흰 바탕·회색 점선 테두리 핀으로 보인다(판정 색·테두리 없음).
      // 오른쪽 "내 화물" 목록에는 넣지 않는다(판정·통관 줄이라서). 지도 아래 WatchedVessels 목록에 따로 있다
      markers.push(...vesselPins.map((v, j) => {
        const letter = markerLetter(active.length + j);
        const when = v.position_at ? dateTime(v.position_at, true) : null;
        const move = v.sog != null ? `${v.sog}노트${v.cog != null ? ` · ${Math.round(v.cog)}°` : ''}` : null;
        const detail = `<div class="watch-tip"><header><strong>${esc(letter)} · ${esc(v.name)}</strong><em class="vessel-only-tag">배만</em></header>`
          + `<span>배만 지켜보는 중 (B/L 없음, 판정 없음)</span>${move ? `<span>${esc(move)}</span>` : ''}${when ? `<span>${esc(when)} 수신</span>` : ''}</div>`;
        const icon = L.divIcon({className: 'watch-pin', iconSize: [34, 34], iconAnchor: [17, 17],
          html: `<span class="pin-body vessel-only"><b>${letter}</b></span>`});
        const label = `${letter} ${v.name} (배만 지켜보는 중)`;
        return L.marker([v.lat as number, v.lng as number], {icon, title: label, alt: label, riseOnHover: true})
          .bindTooltip(detail, {direction: 'auto', offset: [18, 0], className: 'watch-tooltip', opacity: 1})
          .on('click', e => { L.DomEvent.stopPropagation(e); highlight(null); });
      }));
      const layer = L.layerGroup().addTo(map);

      // 목록에서 연 말풍선은 마우스를 떼도 저절로 안 닫힌다. 한 번에 하나만 열어 두고,
      // 다른 배를 고르거나, 다른 마커에 마우스를 올리거나, 지도 빈 곳을 누르면 닫는다 (말풍선이 쌓였다)
      let opened: L.Marker | null = null;
      const closeOpened = () => { opened?.closeTooltip(); opened = null; };
      markers.forEach(m => m.on('mouseover', () => { if (opened && opened !== m) closeOpened(); }));
      map.on('click', () => { closeOpened(); setCluster(null); highlight(null); });

      let groups: number[][] = [];
      const recluster = () => {
        closeOpened();
        layer.clearLayers();
        const pts = spots.map(it => map.latLngToLayerPoint([it.lat, it.lng]));
        const used = new Set<number>();
        groups = [];
        spots.forEach((_, i) => {
          if (used.has(i)) return;
          const g = [i]; used.add(i);
          spots.forEach((__, j) => { if (!used.has(j) && pts[i].distanceTo(pts[j]) < CLUSTER_PX) { g.push(j); used.add(j); } });
          groups.push(g);
        });
        groups.forEach(g => {
          if (g.length === 1) { layer.addLayer(markers[g[0]]); return; }
          const center = L.latLng(g.reduce((a, k) => a + spots[k].lat, 0) / g.length, g.reduce((a, k) => a + spots[k].lng, 0) / g.length);
          // 테두리는 안에서 가장 급한 판정 색(배만 지켜보는 배는 판정이 없어 빠진다). 아래 점은 안에 든 배들의 색(최대 4개, 배만은 회색)
          const urgent = g.some(k => spots[k].cargo?.verdict === 'act') ? 'act' : g.some(k => spots[k].cargo?.verdict === 'watch') ? 'watch' : '';
          const dots = g.slice(0, 4).map(k => `<em style="background:${spotColor(k)}"></em>`).join('');
          const names = g.map(k => `${markerLetter(k)} ${spotName(spots[k])}`).join(', ');
          L.marker(center, {icon: L.divIcon({className: 'watch-cluster', iconSize: [46, 46], iconAnchor: [23, 23],
            html: `<span class="cluster-body ${urgent}"><b>${g.length}</b><i>${dots}</i></span>`}), title: `배 ${g.length}척: ${names}`, alt: `배 ${g.length}척`, riseOnHover: true, zIndexOffset: 1000})
            .on('click', e => { L.DomEvent.stopPropagation(e); closeOpened(); setCluster(g); })
            .bindTooltip(`<div class="watch-tip"><strong>배 ${g.length}척</strong><span>${esc(names)}</span><span>눌러서 자세히 보기</span></div>`, {direction: 'top', offset: [0, -22], className: 'watch-tooltip', opacity: 1})
            .addTo(layer);
        });
        paint();  // 다시 올린 핀에도 강조를 입힌다
      };
      map.on('zoomend', recluster);
      map.on('zoomend', paint);
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
        // 경로 전체가 들어오는 단계가 그보다 낮으면 경로를 포기하고 배를 가운데 두고 그 단계로 확대한다 (사용자 발견:
        // 클러스터 안의 배를 목록에서 누르면 경로 범위에만 맞춰져 그 배로 가지 않았다)
        const here = L.latLng(spots[i].lat, spots[i].lng);
        const apartAt = (z: number) => spots.every((o, j) => j === i
          || map.project(here, z).distanceTo(map.project(L.latLng(o.lat, o.lng), z)) >= CLUSTER_PX);
        let apart = map.getMaxZoom();
        for (let z = map.getMinZoom(); z <= map.getMaxZoom(); z++) { if (apartAt(z)) { apart = z; break; } }
        const track = showTrack ? (spots[i].cargo?.track ?? []) : [];
        const trackBounds = track.length > 1 ? L.latLngBounds(track.map(t => L.latLng(t.lat, t.lng))).pad(.3) : null;
        const trackZoom = trackBounds ? Math.min(map.getBoundsZoom(trackBounds), 9) : 0;
        if (trackBounds && trackZoom >= apart) map.fitBounds(trackBounds, {maxZoom: 9, animate: true});
        else map.setView(here, Math.max(apart, 8), {animate: true});
      };
      fitAll.current = () => { setCluster(null); if (points.length) map.fitBounds(L.latLngBounds([...points, port]).pad(.25), {maxZoom: 8, animate: true}); else map.setView(port, 6, {animate: true}); };

      const ro = new ResizeObserver(() => map.invalidateSize());
      ro.observe(host.current);
      cleanup = () => { hover.current = () => {}; setHovered(null); ro.disconnect(); base.dispose(); map.remove(); };
    });
    return () => { disposed = true; cleanup?.(); };
  }, [list, showTrack, vessels]);  // eslint-disable-line react-hooks/exhaustive-deps

  // 시안 3-3(PC)·3-6(휴대폰): 왼쪽 지도 카드(위에 기준 시각·모든 배 보기·경로 체크), 오른쪽 "내 화물" 목록 카드. 휴대폰은 지도 → 목록 순으로 쌓는다
  return <section className="watch wm" aria-labelledby="watch-title">
    <div className="wm-head"><h2 id="watch-title">지켜보는 화물 지도</h2></div>
    {!list || vessels === null ? <div className="wm-skeleton" role="status" aria-label="지켜보는 화물을 불러오고 있어요."><div className="wm-sk-map"/><div className="wm-sk-list"><i/><i/><i/><i/></div></div>
      // 예전 문장은 "자동으로 추가된다"고 했지만 직접 지켜보기를 눌러야 올라간다
      : !total && !vesselPins.length ? <div className="watch-empty">지켜보는 화물이 없어요. B/L 조회 결과나 선박 옆의 지켜보기 버튼을 누르면 여기에 나와요.</div>
      : <div className="wm-body">
        {<div className="wm-map-card">
          <div className="wm-toolbar">
            <span className="watch-updated">{list.updated_at ? `${dateTime(list.updated_at, true)} 기준` : ''}</span>
            {spots.length > 0 && <button type="button" className="watch-fit" onClick={() => fitAll.current()} title="모든 배 보기" aria-label="모든 배 보기"><Maximize2 size={16} strokeWidth={1.9}/>모든 배 보기</button>}
            {active.length > 0 && <label className="watch-track-toggle"><input type="checkbox" checked={showTrack} onChange={e => setShowTrack(e.target.checked)}/>6시간 간격 경로 보기</label>}
          </div>
          <div className="watch-map">
            <div ref={host} className="leaflet-host"/>
            {cluster && <div className="cluster-panel" role="dialog" aria-label={`이 자리에 있는 배 ${cluster.length}척`} onKeyDown={e => { if (e.key === 'Escape') setCluster(null); }}>
              <div className="cluster-head"><strong>이 자리에 있는 배 {cluster.length}척</strong>
                <button type="button" className="icon-button" onClick={() => setCluster(null)} aria-label="닫기" autoFocus><X size={16}/></button></div>
              <ul>{cluster.map(k => { const v = spots[k]?.vessel; if (v) return <li key={`v${v.mmsi}`}>
                <div className="cluster-item-head"><span className="watch-chip vessel-only">{markerLetter(k)}</span>
                  <span className="watch-main"><strong>{v.name}</strong><small className="vessel-only-note">배만 지켜보는 중 (B/L 없음, 판정 없음)</small></span>
                  <button type="button" className="cluster-go" onClick={() => focus.current(k)} aria-label={`${v.name} 위치로 지도 이동`} title="지도에서 보기"><LocateFixed size={18} strokeWidth={1.9} aria-hidden="true"/></button></div>
                <dl><div><dt>위치 받은 시각</dt><dd>{v.position_at ? dateTime(v.position_at, true) : '확인 안 됨'}</dd></div>
                  {v.sog != null && <div><dt>속력·침로</dt><dd>{`${v.sog}노트${v.cog != null ? ` · ${Math.round(v.cog)}°` : ''}`}</dd></div>}</dl>
              </li>;
                const item = active[k]; const move = motion(item); return <li key={item.bl_masked}>
                <div className="cluster-item-head"><span className="watch-chip" style={{background: colorOf(k)}}>{markerLetter(k)}</span>
                  <span className="watch-main"><strong>{shipOf(item)}</strong>{move && <small>{move}</small>}</span>
                  <button type="button" className="cluster-go" onClick={() => focus.current(k)} aria-label={`${shipOf(item)} 위치로 지도 이동`} title="지도에서 보기"><LocateFixed size={18} strokeWidth={1.9} aria-hidden="true"/></button></div>
                <dl>{rowsOf(item).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
              </li>; })}</ul>
            </div>}
          </div>
        </div>}
        {total > 0 && <aside className="wm-side">
          <div className="wm-side-head"><h3>내 화물</h3>
            <span className="wm-count">진행 중 {active.length + waiting.length}건</span></div>
          <ol ref={listEl} className="watch-list" aria-label="지켜보는 화물">
            {active.map((item, i) => <li key={item.bl_masked} style={{'--i': Math.min(i, 5)} as CSSProperties}>
              <button type="button" className={`${selected === i ? 'selected' : ''} ${hovered === i ? 'hovered' : ''}`.trim()}
                onMouseEnter={() => hover.current(i)} onMouseLeave={() => hover.current(null)} onFocus={() => hover.current(i)} onBlur={() => hover.current(null)} aria-pressed={selected === i} onClick={() => focus.current(i)} aria-label={`${markerLetter(i)} ${shipOf(item)} 지도에서 보기`}>
                <span className="watch-chip" style={{background: colorOf(i)}}>{markerLetter(i)}</span>
                <span className="watch-main">
                  <strong className="watch-goods">{nameOf(item)}</strong>
                  {realShip(item) && realShip(item) !== nameOf(item) && <span className="watch-ship">{item.ship_name}{item.ship_flag ? ` · ${item.ship_flag}` : ''}</span>}
                  <span className="watch-stage">통관 {item.stage ?? '확인 안 됨'}</span>
                  {selected === i && <span className="sr-only">지도에서 선택됨</span>}
                </span>
                <span className="watch-side"><VerdictBadge verdict={item.verdict}/>{!nameOf(item).startsWith('B/L ') && <small className="watch-bl">{item.bl_masked}</small>}</span>
              </button>
            </li>)}
            {/* 위치를 아직 못 받은 화물도 같은 행 모양으로. 지도에는 없어서 눌러도 갈 곳이 없으니 버튼이 아니다 */}
            {waiting.map((item, i) => <li key={item.bl_masked} className="no-pos" style={{'--i': Math.min(active.length + i, 5)} as CSSProperties}>
              <div className="watch-row-static">
                <span className="watch-chip idle" aria-hidden="true">-</span>
                <span className="watch-main">
                  <strong className="watch-goods">{nameOf(item)}</strong>
                  {realShip(item) && realShip(item) !== nameOf(item) && <span className="watch-ship">{item.ship_name}{item.ship_flag ? ` · ${item.ship_flag}` : ''}</span>}
                  <span className="watch-stage">통관 {item.stage ?? '확인 안 됨'}</span>
                </span>
                <span className="watch-side"><VerdictBadge verdict={item.verdict}/>{!nameOf(item).startsWith('B/L ') && <small className="watch-bl">{item.bl_masked}</small>}</span>
              </div>
            </li>)}
          </ol>
          {waiting.length > 0 && <p className="wm-waiting-note">{active.length ? '위치가 없는 화물은 지도에 나오지 않아요.' : '아직 위치를 받지 못했어요. 받는 대로 지도에 나와요.'}</p>}
          {done > 0 && <p className="watch-done">반출이 끝난 화물 {done}건은 지도에서 뺐어요.</p>}
        </aside>}
      </div>}
  </section>;
}
