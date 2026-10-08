'use client';
/** 입항 선박 결과의 지도 (오른쪽 칸 맨 위). 화물 상세의 지도(MapPanel)와 같은 모양과 같은 "지도 펼치기"를 쓴다.
 *
 * 이 지도가 하는 일
 * - 부산항은 항상 보인다. 자세히를 받아 온 배는 모두 점으로 남고(이 세션에서 받은 것), 고른 배만 이름표와 남은 예상 바닷길(점선)이 붙는다
 * - 고른 배가 바뀌면 그 배와 부산이 한 화면에 들어오게 날아간다(움직임 줄이기면 바로 바뀐다)
 * - 표 줄과 같이 반응한다: 줄 위에 올리면 점이 강조되고, 점 위에 올리면 줄이 강조된다. 점을 누르면 그 배를 고른다
 * - 펼치기는 MapPanel과 같은 방식(FLIP): 지도 칸이 작업 공간 전체로 커지고, Esc·줄이기 단추·뒷배경을 누르면 되돌아간다. 모양은 detail.css의 map-* 규칙을 그대로 쓴다
 * 지도는 한 번만 만들고 점·선만 바꿔 끼운다(배를 바꿀 때마다 지도를 새로 만들면 깜빡이고 WebGL 문맥이 낭비된다).
 * 바탕은 lib/basemap.ts: OpenFreeMap 세계 지도, 안 되면 미리 구운 타일, 그것도 안 되면 해안선.
 * 점선은 서버 searoute가 계산한 앞으로의 예상 경로이고 실제 항적이 아니다.
 */
import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {flushSync} from 'react-dom';
import {LocateFixed, Maximize2, Minimize2, Minus, Plus, Route} from 'lucide-react';
import type {Map as LeafletMap, LayerGroup, Marker, Polyline} from 'leaflet';
import {getPresentationData} from '@/lib/api';
import {addBasemap, drawLocalGeography, type Basemap} from '@/lib/basemap';
import {InfoTip} from './VerdictCard';
import type {Freshness} from '@/lib/types';

/** 지도에 올릴 배 한 척. key는 표 줄과 같은 이름(호출부호|선명) */
export interface MapShip {
  key: string; name: string; lat: number; lng: number;
  sog: number | null; cog: number | null; freshness: Freshness;
}

export interface VesselMapProps {
  ships: MapShip[];
  selectedKey: string | null;
  hoverKey: string | null;
  /** 고른 배 → 부산 남은 예상 바닷길 [위도, 경도] */
  route: [number, number][];
  distanceNm: number | null;
  /** 고른 배의 위치를 받지 못했을 때 */
  selectedMissing: boolean;
  onSelect: (key: string) => void;
  onHover: (key: string | null) => void;
}

/** 지도 펼치기 목표 칸(fixed 좌표)과 뒷배경(작업 공간 전체) 좌표. MapPanel과 같은 모양 */
type Box = {bt: number; bl: number; bw: number; bh: number; top: number; left: number; width: number; height: number};
const EASE = 'cubic-bezier(.2,.8,.2,1)';
/** from 칸에서 to 칸으로(to를 기준 크기로) 옮기는 transform. 원점은 왼쪽 위 */
const flip = (from: DOMRect, to: DOMRect) => `translate(${from.left - to.left}px,${from.top - to.top}px) scale(${from.width / to.width},${from.height / to.height})`;
const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** 부산까지 거리로 가장 크게 확대할 단계. 가까우면 항만 앞까지, 멀면 해협 단위로 */
function maxFitZoom(distanceNm: number | null) {
  if (distanceNm == null) return 8;
  if (distanceNm < 30) return 10;
  if (distanceNm < 150) return 9;
  return 8;
}

interface Api {L: typeof import('leaflet'); map: LeafletMap; layer: LayerGroup; base: Basemap; port: [number, number]}

export function VesselMap(p: VesselMapProps) {
  const host = useRef<HTMLDivElement>(null);
  const slot = useRef<HTMLDivElement>(null), frame = useRef<HTMLDivElement>(null), toggle = useRef<HTMLButtonElement>(null);
  const api = useRef<Api | null>(null);
  const markers = useRef(new Map<string, Marker>());
  const line = useRef<Polyline | null>(null);
  const touched = useRef(false), closing = useRef(false);
  // 콜백과 최신 값은 ref로 들고 있어, 지도 이벤트가 옛 값을 잡지 않게 한다
  const latest = useRef(p); latest.current = p;
  const [ready, setReady] = useState(false);
  const [big, setBig] = useState(false), [out, setOut] = useState(false), [box, setBox] = useState<Box | null>(null);

  const selected = p.ships.find(s => s.key === p.selectedKey) ?? null;

  // 1) 지도는 한 번만 만든다
  useEffect(() => {
    let disposed = false;
    let cleanup: (() => void) | undefined;
    void import('leaflet').then(L => {
      if (disposed || !host.current) return;
      const {demo} = getPresentationData();
      const port: [number, number] = [demo.port.lat, demo.port.lng];
      const map = L.map(host.current, {zoomControl: false, scrollWheelZoom: false, minZoom: 4, maxZoom: 10, attributionControl: false});
      // 중심·확대를 먼저 정해야 한다. 정하기 전에 선을 올리면 Leaflet이 화면 범위를 몰라 멈춘다
      map.setView(port, 6, {animate: false});
      map.on('dragstart', () => { touched.current = true; });
      L.control.attribution({position: 'bottomleft', prefix: false}).addTo(map);
      const base = addBasemap(L, map, () => { drawLocalGeography(L, map); });
      L.marker(port, {icon: L.divIcon({className: 'port-marker', html: '<span>⚑</span>', iconSize: [28, 28], iconAnchor: [14, 14]}), title: demo.port.name})
        .addTo(map).bindTooltip(demo.port.name, {permanent: true, direction: 'right', offset: [12, 0], className: 'port-tooltip'});
      const layer = L.layerGroup().addTo(map);
      api.current = {L, map, layer, base, port};
      // 칸 크기가 바뀌면(펼침, 창 크기) 타일이 칸을 채우게 다시 잰다
      const ro = new ResizeObserver(() => { map.invalidateSize(); base.resize(); });
      ro.observe(host.current);
      cleanup = () => { ro.disconnect(); base.dispose(); map.remove(); api.current = null; markers.current.clear(); line.current = null; };
      setReady(true);
    });
    return () => { disposed = true; cleanup?.(); setReady(false); };
  }, []);

  /** 고른 배와 부산(과 남은 경로)이 한 화면에 들어오게 맞춘다. 고른 배가 없으면 부산 주변 */
  function fit(animate: boolean) {
    const a = api.current; if (!a) return;
    const {ships, selectedKey, route, distanceNm} = latest.current;
    const s = ships.find(x => x.key === selectedKey);
    if (!s) { a.map.setView(a.port, 6, {animate: false}); return; }
    const pts = [[s.lat, s.lng], a.port, ...route] as [number, number][];
    const opts = {paddingTopLeft: [64, 64] as [number, number], paddingBottomRight: [64, 64] as [number, number], maxZoom: maxFitZoom(distanceNm)};
    const b = a.L.latLngBounds(pts);
    if (animate && !reduced()) a.map.flyToBounds(b, {...opts, duration: .9}); else a.map.fitBounds(b, {...opts, animate: false});
  }

  // 2) 점과 선: 받아 온 배는 모두 점으로, 고른 배만 이름표와 경로
  useEffect(() => {
    const a = api.current; if (!a || !ready) return;
    const {L, layer} = a;
    layer.clearLayers(); markers.current.clear();
    if (line.current) { line.current.remove(); line.current = null; }
    const css = getComputedStyle(document.documentElement);
    const ordered = [...p.ships.filter(s => s.key !== p.selectedKey), ...p.ships.filter(s => s.key === p.selectedKey)];
    ordered.forEach(s => {
      const sel = s.key === p.selectedKey;
      // ➤ 글자는 기본이 동쪽(90도)을 향한다. 침로는 북쪽이 0도라서 90도를 뺀다
      const rot = (s.cog ?? 0) - 90;
      const icon = L.divIcon({className: `heading-marker${s.freshness === 'stale' ? ' stale' : ''}${sel ? ' sel' : ''}`,
        html: `<span style="transform:rotate(${rot}deg)">➤</span>`, iconSize: [34, 34], iconAnchor: [17, 17]});
      const m = L.marker([s.lat, s.lng], {icon, keyboard: false, zIndexOffset: sel ? 1000 : 0}).addTo(layer);
      const label = `${s.name}${sel && s.sog != null ? ` · ${s.sog} kn` : ''}${sel && s.cog != null ? ` · ${Math.round(s.cog)}°` : ''}`;
      m.bindTooltip(label, {permanent: sel, direction: 'top', offset: [0, -16], className: 'ship-tooltip'});
      m.on('mouseover', () => latest.current.onHover(s.key));
      m.on('mouseout', () => latest.current.onHover(null));
      m.on('click', () => latest.current.onSelect(s.key));
      markers.current.set(s.key, m);
    });
    if (p.selectedKey && p.route.length > 1) {
      line.current = L.polyline(p.route, {color: css.getPropertyValue('--text-2').trim(), weight: 2.5, dashArray: '6 7', opacity: .9, interactive: false}).addTo(a.map);
    }
  }, [ready, p.ships, p.selectedKey, p.route]);

  // 3) 줄 위에 올린 배 강조 (점을 다시 만든 뒤에도 적용되도록 2번 다음에 둔다)
  useEffect(() => {
    markers.current.forEach((m, k) => m.getElement()?.classList.toggle('hl', k === p.hoverKey));
  }, [ready, p.ships, p.selectedKey, p.hoverKey]);

  // 4) 고른 배가 바뀌거나 그 배의 위치가 처음 들어오면 그쪽으로 날아간다
  useEffect(() => {
    if (!ready || !selected) return;
    touched.current = false;
    fit(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, p.selectedKey, selected?.lat, selected?.lng]);

  /** 고른 배만 가운데 두고 확대한다 (부산은 화면 밖일 수 있다) */
  function focusShip() {
    const a = api.current, s = latest.current.ships.find(x => x.key === latest.current.selectedKey); if (!a || !s) return;
    const z = Math.min(maxFitZoom(latest.current.distanceNm) + 1, 10);
    if (reduced()) a.map.setView([s.lat, s.lng], z, {animate: false}); else a.map.flyTo([s.lat, s.lng], z, {duration: .8});
  }

  /** 칸 크기가 바뀐 뒤 Leaflet과 MapLibre 캔버스를 새 크기에 맞춘다 */
  function settle() { api.current?.map.invalidateSize({animate: false}); api.current?.base.resize(); }

  /** 지도 펼치기: 지도 칸을 fixed로 바꿔 작업 공간 전체(상단바 아래, 두 칸 모두)로 키운다. 움직임 줄이기면 바로 바뀐다 (MapPanel과 같은 방식) */
  function open() {
    if (big) return;
    const m = document.querySelector('main')?.getBoundingClientRect(); if (!m) return;
    const g = window.innerWidth <= 700 ? 8 : 16, bottom = Math.min(m.bottom, window.innerHeight);
    setBox({bt: m.top, bl: m.left, bw: m.width, bh: bottom - m.top, top: m.top + g, left: m.left + g, width: m.width - 2 * g, height: bottom - m.top - 2 * g});
    setBig(true);
  }
  function close() {
    if (!big || closing.current) return;
    const f = frame.current, s = slot.current;
    const finish = () => { closing.current = false; setOut(false); flushSync(() => setBig(false)); toggle.current?.focus(); settle(); };
    if (!f || !s || reduced()) { finish(); return; }
    closing.current = true; setOut(true);
    const to = flip(s.getBoundingClientRect(), f.getBoundingClientRect());
    const an = f.animate([{transform: 'none'}, {transform: to}], {duration: 260, easing: EASE, fill: 'forwards'});
    an.onfinish = () => { finish(); an.cancel(); };
  }
  useLayoutEffect(() => {
    const m = api.current?.map;
    if (m) { m.invalidateSize({animate: false}); fit(false); m.scrollWheelZoom[big ? 'enable' : 'disable'](); }
    if (!big) return;
    toggle.current?.focus(); document.body.dataset.mapBig = '1';
    const f = frame.current, s = slot.current;
    if (f && s && !reduced()) f.animate([{transform: flip(s.getBoundingClientRect(), f.getBoundingClientRect())}, {transform: 'none'}], {duration: 320, easing: EASE});
    // 펼침 애니메이션이 끝난 뒤 한 번 더 맞춘다(타일이 칸을 가득 채우게)
    const t = window.setTimeout(() => { settle(); fit(false); }, reduced() ? 0 : 340);
    return () => { window.clearTimeout(t); delete document.body.dataset.mapBig; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [big]);
  // 펼친 동안 Esc로 닫는다
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && big) { e.preventDefault(); close(); } };
    document.addEventListener('keydown', onKey); return () => document.removeEventListener('keydown', onKey);
  });
  // 펼친 동안 Tab이 지도 밖으로 나가지 않게 가둔다
  function trap(e: React.KeyboardEvent) {
    if (e.key !== 'Tab' || !big) return;
    const els = [...(frame.current?.querySelectorAll<HTMLElement>('button,summary,a[href],[tabindex="0"]') ?? [])].filter(x => !x.hasAttribute('disabled'));
    if (!els.length) return;
    const first = els[0], last = els[els.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  const zoom = (d: 1 | -1) => { touched.current = true; const m = api.current?.map; if (m) d > 0 ? m.zoomIn() : m.zoomOut(); };

  return <section className={`map-section vmap${big ? ' big' : ''}`} aria-label="입항 선박 지도예요. 화살표는 배가 가는 방향이에요">
    {big && box && <div className={`map-backdrop${out ? ' out' : ''}`} style={{top: box.bt, left: box.bl, width: box.bw, height: box.bh}} onClick={close} aria-hidden="true"/>}
    <div ref={slot} className="map-slot">
      <div ref={frame} className={`map-frame${big ? ' is-overlay' : ''}`} style={big && box ? {top: box.top, left: box.left, width: box.width, height: box.height} : undefined}
        role={big ? 'dialog' : undefined} aria-modal={big ? true : undefined} aria-label={big ? '지도 크게 보기' : undefined} onKeyDown={trap}>
        <div ref={host} className="leaflet-host" role="region" aria-label="부산항과 입항 선박 위치 지도"/>
        <div className="map-chips">
          {p.selectedMissing && <span className="map-chip">이 배의 위치를 받지 못했어요</span>}
          {!p.selectedMissing && !selected && <span className="map-chip">배를 고르면 지금 위치가 보여요</span>}
          {p.route.length > 1 && <InfoTip label="점선 설명">점선은 지금 위치에서 부산까지 갈 예상 경로예요. 지나온 길이 아니에요.</InfoTip>}
        </div>
        <div className="map-tools">
          <button ref={toggle} type="button" className="map-tool map-expand" aria-pressed={big} aria-label={big ? '지도 줄이기' : '지도 펼치기'} title={big ? '지도 줄이기 (Esc)' : '지도 펼치기'} onClick={big ? close : open}>{big ? <Minimize2 size={18}/> : <Maximize2 size={18}/>}</button>
        </div>
        <div className="map-zoom">
          <button type="button" className="map-tool" aria-label="지도 확대" title="확대" onClick={() => zoom(1)}><Plus size={18}/></button>
          <button type="button" className="map-tool" aria-label="지도 축소" title="축소" onClick={() => zoom(-1)}><Minus size={18}/></button>
          <button type="button" className="map-tool" aria-label="고른 배로 이동" title="고른 배로 이동" disabled={!selected} onClick={() => { touched.current = true; focusShip(); }}><LocateFixed size={18}/></button>
          <button type="button" className="map-tool" aria-label="부산까지 전체 경로 보기" title="부산까지 전체 경로 보기" disabled={!selected} onClick={() => { touched.current = false; fit(true); }}><Route size={18}/></button>
        </div>
      </div>
    </div>
  </section>;
}
