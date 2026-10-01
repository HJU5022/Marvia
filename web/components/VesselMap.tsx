'use client';
/** 선박 자세히 보기 전용 지도 (docs/specs/chat-search.md "선박 자세히 보기"). 화물 화면의 MapPanel은 그대로 둔다.
 *
 * MapPanel과 다른 점 (10-01 사용자 요청: 확대해서 배가 어디서 어디로 움직이는지 읽히게)
 * - 배를 가운데 두고 확대해서 시작한다. 부산까지 가까울수록 더 확대한다
 * - 배 모양을 침로(cog) 방향으로 돌리고, 선명·속력·침로를 라벨로 붙인다
 * - 부산까지 남은 예상 바닷길(서버 searoute 계산)을 점선으로 그린다. 실제 항적이 아니다
 * 외부 지도 타일을 부르지 않는다. 레포에 넣은 Natural Earth 해안선만 쓰므로 너무 확대하면 해안선이 거칠다(최대 10단계).
 */
import {useEffect, useRef} from 'react';
import {Maximize2, Navigation} from 'lucide-react';
import type {GeoJsonObject} from 'geojson';
import {getGeography, getPresentationData} from '@/lib/api';
import {dateTime} from '@/lib/format';
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

/** 부산까지 거리로 시작 확대 단계를 고른다. 가까우면 항만 앞까지, 멀면 해협 단위로 */
function startZoom(distanceNm: number | null) {
  if (distanceNm == null) return 7;
  if (distanceNm < 30) return 9;
  if (distanceNm < 150) return 8;
  return 6;
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
      L.geoJSON(getGeography() as GeoJsonObject, {
        style: {color: color('--coast'), weight: 1, fillColor: color('--land'), fillOpacity: 1}, interactive: false,
      }).addTo(map);
      map.attributionControl.setPrefix(false).addAttribution('Leaflet · Natural Earth (public domain)');

      // 남은 예상 바닷길: 점선. 실제 항적이 아니다
      const line = p.route.length > 1 ? L.polyline(p.route, {color: color('--accent-dark'), weight: 2.5, dashArray: '6 7', opacity: .9, interactive: false}).addTo(map) : null;

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
      map.setView(ship, startZoom(p.distanceNm), {animate: false});

      // 펼침 애니메이션 뒤 크기를 다시 잰다
      const ro = new ResizeObserver(() => map.invalidateSize());
      ro.observe(host.current);
      cleanup = () => { ro.disconnect(); map.remove(); };
    });
    return () => { disposed = true; cleanup?.(); };
  }, [p.lat, p.lng, p.cog, p.sog, p.name, p.freshness, p.distanceNm, p.route]);

  return <section className="vessel-map" aria-label={`${p.name} 현재 위치 지도`}>
    <div className="vessel-map-frame">
      <div ref={host} className="leaflet-host"/>
      <div className="vessel-map-tools">
        <button type="button" className="icon-button" onClick={() => focus.current()} title="배로 돌아가기" aria-label="배로 돌아가기"><Navigation size={15}/></button>
        <button type="button" className="icon-button" onClick={() => fitAll.current()} title="부산까지 전체 경로 보기" aria-label="부산까지 전체 경로 보기"><Maximize2 size={15}/></button>
      </div>
      <div className="vessel-map-caption mono">{p.lat.toFixed(2)}° N · {p.lng.toFixed(2)}° E<small>{p.lastTime ? `${dateTime(p.lastTime, true)} 수신` : '수신 시각 확인되지 않음'}</small></div>
    </div>
    <p className="vessel-map-note"><span className="legend-line"/>부산까지 남은 예상 바닷길(계산값, 실제 항적 아님) · 화살표는 진행 방향(침로)</p>
  </section>;
}
