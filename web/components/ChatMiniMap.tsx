'use client';
/** 채팅 말풍선 아래 작은 지도. 위치를 조회한 답일 때만 그려서, 아래 큰 지도까지 내려가지 않고도 배가 어디쯤인지 보이게 한다 (10-05 결정).
 * 지도 설정은 MapPanel과 같다: 레포에 넣은 Natural Earth 해안선만 쓰고 외부 타일을 부르지 않는다(next.config.ts), leaflet은 브라우저에서만 불러온다.
 * 배 한 점과 부산항 한 점만 보여 주고, 조작은 막는다(말풍선 안에서 스크롤을 가로채지 않게). 자세한 조작은 "크게 보기"로 큰 지도에서 한다.
 * 값은 서버가 준 위치 그대로다. 없는 값(이름, 거리, 수신 시각)은 지어내지 않고 문구에서 뺀다.
 */
import {useEffect, useRef, useState} from 'react';
import {Maximize2} from 'lucide-react';
import type {GeoJsonObject} from 'geojson';
import {getGeography, getPresentationData} from '@/lib/api';
import {dateTime} from '@/lib/format';
import type {ChatMap} from '@/lib/types';

/** 큰 지도(MapPanel)로 화면을 옮기고 포커스를 준다. 큰 지도가 없는 화면(선박 표 등)이면 아무 일도 하지 않는다.
 * 움직임 줄이기를 켠 사용자에게는 부드러운 스크롤을 쓰지 않는다 */
function goBigMap() {
  const el = document.getElementById('big-map');
  if (!el) return;
  el.scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start'});
  el.focus({preventScroll: true});
}

export function ChatMiniMap({map: m}: {map: ChatMap}) {
  const host = useRef<HTMLDivElement>(null);
  const name = m.ship_name ?? '선박';
  // 한 줄 설명. 있는 값만 이어 붙인다
  const parts = [name, m.distance_nm != null ? `부산까지 약 ${Math.round(m.distance_nm)}해리` : null, m.received_at ? `${dateTime(m.received_at, true)} 수신` : null].filter(Boolean);
  const caption = parts.join(' · ');

  // 큰 지도가 화면에 있을 때만 "크게 보기"를 보인다. 화물 결과가 없는 답(목록에서 고른 다른 배의 위치 등)에서는 눌러도 갈 곳이 없다 (10-05)
  const [hasBig,setHasBig] = useState(false);
  useEffect(() => { setHasBig(!!document.getElementById('big-map')); }, []);
  useEffect(() => {
    let disposed = false;
    let cleanup: (() => void) | undefined;
    void import('leaflet').then(L => {
      if (disposed || !host.current) return;
      const {demo} = getPresentationData();
      const css = getComputedStyle(document.documentElement);
      const color = (n: string) => css.getPropertyValue(n).trim();
      const ship: L.LatLngTuple = [m.lat, m.lng];
      const port: L.LatLngTuple = [demo.port.lat, demo.port.lng];
      // 조작을 모두 막은 고정 지도. 배와 부산항이 함께 들어오게 맞춘다 (먼저 화면 범위를 정한 뒤 선을 올린다, VesselMap 10-01 메모)
      const map = L.map(host.current, {zoomControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false, touchZoom: false, boxZoom: false, keyboard: false, minZoom: 4, maxZoom: 10, attributionControl: true});
      map.fitBounds(L.latLngBounds([ship, port]).pad(.5), {maxZoom: 8, animate: false});
      L.geoJSON(getGeography() as GeoJsonObject, {style: {color: color('--coast'), weight: 1, fillColor: color('--land'), fillOpacity: 1}, interactive: false}).addTo(map);
      L.polyline([ship, port], {color: color('--blue'), weight: 2, dashArray: '5 7', opacity: .8, interactive: false}).addTo(map);
      L.marker(port, {icon: L.divIcon({className: 'port-marker', html: '<span>⚑</span>', iconSize: [28, 28], iconAnchor: [14, 14]}), interactive: false, keyboard: false}).addTo(map);
      L.marker(ship, {icon: L.divIcon({className: 'ship-marker', html: '<span>▲</span>', iconSize: [30, 30], iconAnchor: [15, 15]}), interactive: false, keyboard: false}).addTo(map);
      map.attributionControl.setPrefix(false).addAttribution('Leaflet · Natural Earth');
      const ro = new ResizeObserver(() => map.invalidateSize());
      ro.observe(host.current);
      cleanup = () => { ro.disconnect(); map.remove(); };
    });
    return () => { disposed = true; cleanup?.(); };
  }, [m.lat, m.lng]);

  return <figure className="chat-mini-map">
    <div ref={host} className="chat-mini-map-host" role="img" aria-label={`${name} 현재 위치 지도. 위도 ${m.lat.toFixed(2)}, 경도 ${m.lng.toFixed(2)}${m.distance_nm != null ? `, 부산까지 약 ${Math.round(m.distance_nm)}해리` : ''}`}/>
    <figcaption><span>{caption}</span>
      {hasBig && <button type="button" onClick={goBigMap}><Maximize2 size={13}/>크게 보기</button>}</figcaption>
  </figure>;
}
