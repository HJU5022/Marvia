'use client';
/** 채팅 말풍선 아래 작은 지도. 위치를 조회한 답일 때만 그려서, 아래 큰 지도까지 내려가지 않고도 배가 어디쯤인지 보이게 한다.
 * 지도 설정은 MapPanel과 같다: 바탕은 lib/basemap.ts의 세계 지도이고 안 되면 해안선으로 되돌린다, leaflet은 브라우저에서만 불러온다.
 * 배 한 점과 부산항 한 점만 보여 주고, 조작은 막는다(말풍선 안에서 스크롤을 가로채지 않게). 자세한 조작은 "크게 보기"로 큰 지도에서 한다.
 * 값은 서버가 준 위치 그대로다. 없는 값(이름, 거리, 수신 시각)은 지어내지 않고 문구에서 뺀다.
 */
import {useEffect, useRef, useState} from 'react';
import {Maximize2} from 'lucide-react';
import {getPresentationData} from '@/lib/api';
import {addBasemap, drawLocalGeography} from '@/lib/basemap';
import {dateTime} from '@/lib/format';
import type {ChatMap} from '@/lib/types';

/** 큰 지도(MapPanel)를 작업 공간 전체로 펼친다. 큰 지도가 없는 화면(선박 표 등)이면 아무 일도 하지 않는다.
 * 휴대폰에서 상세 시트가 접혀 있으면 먼저 시트를 올린 뒤(옮겨 다니는 칸 안에서는 fixed 지도가 어긋난다) 시트가 멈춘 다음 펼친다 */
function goBigMap() {
  if (!document.getElementById('big-map')) return;
  const folded = !!document.querySelector('.chat-app:not(.sheet-open)');
  if (folded) window.dispatchEvent(new Event('marvia:sheet-open'));
  setTimeout(() => window.dispatchEvent(new Event('marvia:map-expand')), folded ? 340 : 0);
}

export function ChatMiniMap({map: m}: {map: ChatMap}) {
  const host = useRef<HTMLDivElement>(null);
  // 이름이 없을 때 그냥 "선박"이라 쓰면 어떤 배인지 알 수 없다. 서버가 같은 배로 확인한 때만 이름을 주므로(chat.py _map_from), 없으면 이름 모름을 그대로 밝힌다
  const name = m.ship_name ?? '선박 (이름 확인 안 됨)';
  // 위치 값이 비었거나 0,0이면 지도를 그리지 않는다 (실패한 답에 지도가 붙던 문제의 화면 쪽 방어)
  const valid = Number.isFinite(m.lat) && Number.isFinite(m.lng) && !(m.lat === 0 && m.lng === 0);
  // 한 줄 설명. 있는 값만 이어 붙인다
  const sub = [m.distance_nm != null ? `부산까지 바닷길로 약 ${Math.round(m.distance_nm)}해리` : null, m.received_at ? `${dateTime(m.received_at, true)} 기준` : null].filter(Boolean).join(' · ');

  // 큰 지도가 화면에 있을 때만 "크게 보기"를 보인다. 화물 결과가 없는 답(목록에서 고른 다른 배의 위치 등)에서는 눌러도 갈 곳이 없다
  const [hasBig,setHasBig] = useState(false);
  useEffect(() => { setHasBig(!!document.getElementById('big-map')); }, []);
  useEffect(() => {
    if (!valid) return;
    let disposed = false;
    let cleanup: (() => void) | undefined;
    void import('leaflet').then(L => {
      if (disposed || !host.current) return;
      const {demo} = getPresentationData();
      const ship: L.LatLngTuple = [m.lat, m.lng];
      const port: L.LatLngTuple = [demo.port.lat, demo.port.lng];
      // 조작을 모두 막은 고정 지도. 배와 부산항이 함께 들어오게 맞춘다 (먼저 화면 범위를 정한 뒤 선을 올린다, VesselMap)
      const map = L.map(host.current, {zoomControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false, touchZoom: false, boxZoom: false, keyboard: false, minZoom: 4, maxZoom: 10, attributionControl: true});
      map.fitBounds(L.latLngBounds([ship, port]).pad(.5), {maxZoom: 8, animate: false});
      const base = addBasemap(L, map, () => { drawLocalGeography(L, map); });
      // 배와 부산항을 잇던 점선 직선은 실제 항로가 아니라 육지를 가로질러 보였다. 항로 데이터가 없으므로 선을 없애고 두 점만 둔다
      L.marker(port, {icon: L.divIcon({className: 'port-marker', html: '<span>⚑</span>', iconSize: [28, 28], iconAnchor: [14, 14]}), interactive: false, keyboard: false}).addTo(map);
      L.marker(ship, {icon: L.divIcon({className: 'ship-marker', html: '<span>▲</span>', iconSize: [30, 30], iconAnchor: [15, 15]}), interactive: false, keyboard: false}).addTo(map);
      map.attributionControl.setPrefix(false);
      const ro = new ResizeObserver(() => map.invalidateSize());
      ro.observe(host.current);
      cleanup = () => { ro.disconnect(); base.dispose(); map.remove(); };
    });
    return () => { disposed = true; cleanup?.(); };
  }, [m.lat, m.lng, valid]);

  if (!valid) return null;
  return <figure className="chat-mini-map">
    <div ref={host} className="chat-mini-map-host" role="img" aria-label={`${name} 현재 위치 지도. 위도 ${m.lat.toFixed(2)}, 경도 ${m.lng.toFixed(2)}${m.distance_nm != null ? `, 부산까지 약 ${Math.round(m.distance_nm)}해리` : ''}`}/>
    <figcaption><span><strong>{name}</strong>{sub && <small>{sub}</small>}
      {/* 지도에 아무 설명이 없었다. 점이 무엇인지와 거리가 근사값임을 밝힌다 */}
      <small className="mini-map-legend">▲ 배의 현재 위치 · ⚑ 부산항 · 거리는 바닷길 기준 근사값이에요</small></span>
      {hasBig && <button type="button" onClick={goBigMap} aria-label="크게 보기" title="지도 크게 보기"><Maximize2 size={16}/></button>}</figcaption>
  </figure>;
}
