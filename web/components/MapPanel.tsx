'use client';
/** Real Leaflet map with locally bundled Natural Earth GeoJSON. E4, no tile/API calls.
 * The line points toward Busan; it is explicitly not a measured track or searoute.
 */
import {useEffect,useRef} from 'react';
import {LocateFixed,Navigation} from 'lucide-react';
import type {GeoJsonObject} from 'geojson';
import type {AgentResponse} from '@/lib/types';
import {getGeography,getPresentationData} from '@/lib/api';
import {dateTime} from '@/lib/format';
import {SectionTitle} from './Shared';
export function MapPanel({response:r}:{response:AgentResponse}) {
 const host=useRef<HTMLDivElement>(null); const reset=useRef<()=>void>(()=>{});const p=r.position; const stale=p?.freshness==='stale';
 useEffect(()=>{let disposed=false;let cleanup:undefined|(()=>void);
  void import('leaflet').then(L=>{if(disposed||!host.current)return;const {demo}=getPresentationData();const colors=getComputedStyle(document.documentElement);const color=(name:string)=>colors.getPropertyValue(name).trim();const port:L.LatLngTuple=[demo.port.lat,demo.port.lng];const position:L.LatLngTuple|null=p?[p.lat,p.lng]:null;
   const map=L.map(host.current,{zoomControl:true,scrollWheelZoom:false,minZoom:4,maxZoom:10,attributionControl:true});
   const home=()=>{if(position)map.fitBounds(L.latLngBounds([position,port]).pad(.65),{maxZoom:7,animate:false});else map.setView(port,6);};home();reset.current=home;
   L.geoJSON(getGeography() as GeoJsonObject,{style:{color:color('--coast'),weight:1,fillColor:color('--land'),fillOpacity:1},interactive:false}).addTo(map);
   for(let lat=25;lat<42;lat+=1)L.polyline([[lat,118],[lat,144]],{color:color('--muted'),weight:.6,opacity:.18,interactive:false}).addTo(map);
   for(let lng=119;lng<144;lng+=1)L.polyline([[25,lng],[42,lng]],{color:color('--muted'),weight:.6,opacity:.18,interactive:false}).addTo(map);
   demo.map_labels.forEach(label=>L.marker([label.lat,label.lng],{icon:L.divIcon({className:'map-place',html:label.name,iconSize:[80,20]}),interactive:false}).addTo(map));
   const portMarker=L.marker(port,{icon:L.divIcon({className:'port-marker',html:'<span>⚑</span>',iconSize:[28,28],iconAnchor:[14,14]}),title:demo.port.name}).addTo(map);
   portMarker.bindTooltip(demo.port.name,{permanent:true,direction:'right',className:'port-tooltip'});
   if(position){L.polyline([position,port],{color:color(stale?'--muted':'--blue'),weight:2,dashArray:'5 7',opacity:stale?.4:.8,interactive:false}).addTo(map);
    L.circle(position,{radius:stale?14000:11000,color:color(stale?'--muted':'--blue'),weight:1,dashArray:stale?'4 5':undefined,fillOpacity:.08}).addTo(map);
    const ship=L.marker(position,{icon:L.divIcon({className:`ship-marker ${stale?'stale':''}`,html:'<span>▲</span>',iconSize:[30,30],iconAnchor:[15,15]}),title:stale?'마지막 수신 위치':'수신 위치',opacity:stale?.45:1}).addTo(map);
    const tip=document.createElement('span');tip.textContent=r.vessel?.name??'선박 수신 위치';ship.bindTooltip(tip,{permanent:true,direction:'bottom',className:'ship-tooltip',offset:[0,16]});
   }
   map.attributionControl.setPrefix(false);map.attributionControl.addAttribution('Leaflet · Natural Earth (public domain)');
   const observer=new ResizeObserver(()=>map.invalidateSize());observer.observe(host.current);cleanup=()=>{observer.disconnect();map.remove();};
  });return()=>{disposed=true;cleanup?.();};
 },[p,r.vessel?.name,stale]);
 return <section id="big-map" tabIndex={-1} className={`map-section ${stale?'map-stale':''}`}><SectionTitle label={stale?'마지막 수신 위치':p?'선박과 부산항의 위치':'부산항 기준 지도'} kicker="VESSEL POSITION" side={<span className={`freshness ${p?.freshness??'unknown'}`}><span/>{p?.freshness==='fresh'?'수신 정상':stale?'오래된 위치':'위치 미확인'}</span>}/><div className="map-frame"><div ref={host} className="leaflet-host" role="region" aria-label="부산항과 선박 수신 위치 지도"/><div className="map-compass" aria-hidden="true"><span>N</span><Navigation size={20}/></div><button className="map-reset" onClick={()=>reset.current()} aria-label="선박과 부산항에 지도 맞추기"><LocateFixed size={18}/></button><div className="map-caption">{p?<><span className="mono">{p.lat.toFixed(2)}° N &nbsp; {p.lng.toFixed(2)}° E</span><small>{dateTime(p.last_time,true)} 수신{stale?' · 현재 위치 아님':''}</small></>:<span>선박 위치 없음 · 부산항 기준 위치</span>}</div></div><p className="map-note">점선은 목적항 방향 안내이며 실제 항적이 아닙니다. 지형은 로컬 지도 데이터입니다.</p></section>;
}
