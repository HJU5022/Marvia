'use client';
/** 선박 자세히 보기 전용 지도 (docs/specs/chat-search.md "선박 자세히 보기"). 화물 화면의 MapPanel은 그대로 둔다.
 *
 * MapPanel과 다른 점 (10-01 사용자 요청: 확대해서 배가 어디서 어디로 움직이는지 읽히게)
 * - 배를 가운데 두고 확대해서 시작한다(30해리 안 10, 150해리 안 9, 그 밖 7단계). 부산까지 가까울수록 더 확대한다
 * - 배 모양을 침로(cog) 방향으로 돌리고, 선명·속력·침로를 라벨로 붙인다
 * - 부산까지 남은 예상 바닷길(서버 searoute 계산)을 점선으로 그린다. 실제 항적이 아니다
 * 바탕은 lib/basemap.ts의 세계 지도다(10-06). 못 쓰면 레포의 Natural Earth 해안선으로 되돌리며, 그때는 너무 확대하면 해안선이 거칠다(최대 10단계).
 */
import {useEffect, useRef} from 'react';
import {LocateFixed, Route} from 'lucide-react';
import {getPresentationData} from '@/lib/api';
import {addBasemap, drawLocalGeography} from '@/lib/basemap';
import type {Freshness} from '@/lib/types';

export interface VesselMapProps {
  name: string;
  lat: number; lng: number;
  sog: number | null; cog: number | null;
  freshness: Freshness;
  lastTime: string | null;
  route: [number, number][];   // 배 → 부산 남은 예상 바닷길 [위도, 경도]
  distanceNm: number | null;
}

/** 부산까지 거리로 시작 확대 단계를 고른다. 가까우면 항만 앞까지, 멀면 해협 단위로.
 * 10-01 사용자 요청으로 한 단계씩 더 확대(9/8/6 → 10/9/7). 10은 이 지도의 최대라 해안선이 조금 거칠다 */
function startZoom(distanceNm: number | null) {
  if (distanceNm == null) return 8;
  if (distanceNm < 30) return 10;
  if (distanceNm < 150) return 9;
  return 7;
}

export function VesselMap(p: VesselMapProps) {
  const host = useRef<HTMLDivElement>(null);
  const fitAll = useRef<() => void>(() => {});
  const focus = useRef<() => void>(() => {});

  useEffect(() => {
    let disposed = false;
    let cleanup: (() => void) | undefined;
    void import('leaflet').then(L => {
      if (disposed || !host.current) return;
      const {demo} = getPresentationData();
      const css = getComputedStyle(document.documentElement);
      const color = (name: string) => css.getPropertyValue(name).trim();
      const ship: L.LatLngTuple = [p.lat, p.lng];
      const port: L.LatLngTuple = [demo.port.lat, demo.port.lng];

      const map = L.map(host.current, {zoomControl: true, scrollWheelZoom: true, minZoom: 4, maxZoom: 10, attributionControl: true});
      // 중심·확대를 먼저 정해야 한다. 정하기 전에 선(해안선·경로)을 올리면 Leaflet이 화면 범위를 몰라 멈춘다
      // (10-01 "Cannot read properties of undefined (reading 'min')", 배가 아예 안 보였다)
      map.setView(ship, startZoom(p.distanceNm), {animate: false});
      const base = addBasemap(L, map, () => { drawLocalGeography(L, map); });
      map.attributionControl.setPrefix(false);

      // 남은 예상 바닷길: 점선. 실제 항적이 아니다
      const line = p.route.length > 1 ? L.polyline(p.route, {color: color('--text-2'), weight: 2.5, dashArray: '6 7', opacity: .9, interactive: false}).addTo(map) : null;

      // 부산항
      L.marker(port, {icon: L.divIcon({className: 'port-marker', html: '<span>⚑</span>', iconSize: [28, 28], iconAnchor: [14, 14]}), interactive: false})
        .addTo(map).bindTooltip('부산항', {permanent: true, direction: 'right', offset: [12, 0], className: 'port-tooltip'});

      // 배: 침로 방향으로 돌린 화살표. 침로를 모르면 위쪽 그대로. 오래된 위치는 흐리게
      // ➤ 글자는 기본이 동쪽(90°)을 향한다. 침로는 북쪽이 0°라서 90°를 뺀다
      const rot = (p.cog ?? 0) - 90;
      const icon = L.divIcon({className: `heading-marker ${p.freshness === 'stale' ? 'stale' : ''}`,
        html: `<span style="transform:rotate(${rot}deg)">➤</span>`, iconSize: [34, 34], iconAnchor: [17, 17]});
      const label = `${p.name}${p.sog != null ? ` · ${p.sog} kn` : ''}${p.cog != null ? ` · ${Math.round(p.cog)}°` : ''}`;
      L.marker(ship, {icon, keyboard: false}).addTo(map)
        .bindTooltip(label, {permanent: true, direction: 'top', offset: [0, -16], className: 'ship-tooltip'});

      focus.current = () => map.setView(ship, startZoom(p.distanceNm), {animate: true});
      fitAll.current = () => map.fitBounds(L.latLngBounds(line ? line.getLatLngs() as L.LatLng[] : [L.latLng(ship), L.latLng(port)]).pad(.15), {maxZoom: 9, animate: true});

      // 펼침 애니메이션 뒤 크기를 다시 잰다
      const ro = new ResizeObserver(() => map.invalidateSize());
      ro.observe(host.current);
      cleanup = () => { ro.disconnect(); base.dispose(); map.remove(); };
    });
    return () => { disposed = true; cleanup?.(); };
  }, [p.lat, p.lng, p.cog, p.sog, p.name, p.freshness, p.distanceNm, p.route]);

  // 시안 2-4: 지도 위에 작은 칩 둘. 좌표·수신 시각은 오른쪽 "선박 위치" 칸에 이미 있어 지도 안에서는 뺐다
  return <section className="vessel-map" aria-label={`${p.name} 현재 위치 지도예요. 화살표는 진행 방향이에요`}>
    <div className="vessel-map-frame">
      <div ref={host} className="leaflet-host"/>
      <span className="vm-chip vm-bottom">실제로 지나온 길이 아닌 예상 경로</span>
      <div className="vessel-map-tools">
        <button type="button" className="icon-button" onClick={() => focus.current()} title="배로 돌아가기" aria-label="배로 돌아가기"><LocateFixed size={18} strokeWidth={1.75}/></button>
        <button type="button" className="icon-button" onClick={() => fitAll.current()} title="부산까지 전체 경로 보기" aria-label="부산까지 전체 경로 보기"><Route size={18} strokeWidth={1.75}/></button>
      </div>
    </div>
  </section>;
}
