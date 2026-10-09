'use client';
/** Leaflet 지도. 바탕은 OpenFreeMap 세계 지도(lib/basemap.ts), 안 되면 레포의 Natural Earth 해안선으로 되돌린다.
 * The line points toward Busan; it is explicitly not a measured track or searoute.
 */
import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {flushSync} from 'react-dom';
import {LocateFixed,Maximize2,Minimize2,Minus,Plus} from 'lucide-react';
import type {Map as LeafletMap} from 'leaflet';
import type {ReactNode} from 'react';
import type {AgentResponse} from '@/lib/types';
import {getPresentationData} from '@/lib/api';
import {addBasemap,drawLocalGeography,type Basemap} from '@/lib/basemap';
import {countryLabel,dateTime,sourceLabels,verdictLabels} from '@/lib/format';
import {conflictBadge,InfoTip} from './VerdictCard';
/** 지도 펼치기 목표 칸(fixed 좌표)과 뒷배경(작업 공간 전체) 좌표 */
type Box={bt:number;bl:number;bw:number;bh:number;top:number;left:number;width:number;height:number};
const EASE='cubic-bezier(.2,.8,.2,1)';
/** from 칸에서 to 칸으로(to를 기준 크기로) 옮기는 transform. 원점은 왼쪽 위(CSS transform-origin) */
function flip(from:DOMRect,to:DOMRect){return `translate(${from.left-to.left}px,${from.top-to.top}px) scale(${from.width/to.width},${from.height/to.height})`;}
/** 상세 패널의 맨 위 지도. 지도 위에 작은 카드(등급 배지 + 지켜보기 + 선명(국적) + 부산까지 거리)가 떠 있다 (마누스 시안 2-2, 01_공통 "상세 패널").
 * watch는 page.tsx가 로그인·실제 모드일 때만 넘기는 WatchToggle이다. 품명(customs.goods_name)은 있을 때만 선명 앞에 붙는다. */
export function MapPanel({response:r,watch}:{response:AgentResponse;watch?:ReactNode}) {
 const host=useRef<HTMLDivElement>(null);const card=useRef<HTMLDivElement>(null); const reset=useRef<()=>void>(()=>{});const slot=useRef<HTMLDivElement>(null),frame=useRef<HTMLDivElement>(null),toggle=useRef<HTMLButtonElement>(null),mapRef=useRef<LeafletMap|null>(null),closing=useRef(false),touched=useRef(false),baseRef=useRef<Basemap|null>(null);
 const [big,setBig]=useState(false);const [out,setOut]=useState(false);const [box,setBox]=useState<Box|null>(null);const p=r.position; const stale=p?.freshness==='stale';
 useEffect(()=>{let disposed=false;let cleanup:undefined|(()=>void);
  void import('leaflet').then(L=>{if(disposed||!host.current)return;const {demo}=getPresentationData();const colors=getComputedStyle(document.documentElement);const color=(name:string)=>colors.getPropertyValue(name).trim();const port:L.LatLngTuple=[demo.port.lat,demo.port.lng];const position:L.LatLngTuple|null=p?[p.lat,p.lng]:null;
   // 펼치기는 오른쪽 위, 확대·축소·맞추기는 왼쪽 아래 아이콘 단추(map-tools, map-zoom)가 맡는다. 아래 오른쪽은 떠 있는 카드가 쓰므로 저작자 표시는 왼쪽 아래로 보낸다
   const map=L.map(host.current,{zoomControl:false,scrollWheelZoom:false,minZoom:4,maxZoom:10,attributionControl:false});
   mapRef.current=map;touched.current=false;map.on('dragstart',()=>{touched.current=true;});L.control.attribution({position:'bottomleft',prefix:false}).addTo(map);
   // 직접 쓴 바다·나라 이름은 세계 지도를 못 쓰는 되돌림 때만 올라온다(세계 지도에는 이름이 이미 있다). 그 이름이 배와 부산항 표시(마커와 이름표)에 겹치면 그 이름만 숨긴다. 확대·이동 때마다 다시 계산한다
   const labels:{el:()=>HTMLElement|undefined;ll:L.LatLngTuple}[]=[];const hideNearLabels=()=>{const pts=[port,...(position?[position]:[])].map(q=>map.latLngToContainerPoint(q));
    labels.forEach(l=>{const el=l.el();if(!el)return;const q=map.latLngToContainerPoint(l.ll);el.classList.toggle('map-place-hide',pts.some(a=>Math.abs(q.x-a.x)<110&&Math.abs(q.y-a.y)<46));});};
   map.on('zoomend moveend',hideNearLabels);
   // 요약 줄(판정·선명·거리)은 지도 아래로 옮겼다. 지도 위에는 배와 부산항뿐이라 여백은 사방 같게 둔다
   const home=()=>{if(!position){map.setView(port,6);return;}
    map.invalidateSize();map.fitBounds(L.latLngBounds([position,port]),{maxZoom:8,animate:false,padding:[56,56]});hideNearLabels();};
home();reset.current=home;
   // 바탕: 세계 지도. 못 쓰면(WebGL 없음, 4초 안에 안 옴, 오류) 예전 해안선과 격자, 손으로 쓴 이름표로 되돌린다. 모두 마커·경로 밑에 깔린다
   baseRef.current=addBasemap(L,map,()=>{
    for(let lat=25;lat<42;lat+=1)L.polyline([[lat,118],[lat,144]],{color:color('--muted'),weight:.6,opacity:.18,interactive:false}).addTo(map).bringToBack();
    for(let lng=119;lng<144;lng+=1)L.polyline([[25,lng],[42,lng]],{color:color('--muted'),weight:.6,opacity:.18,interactive:false}).addTo(map).bringToBack();
    drawLocalGeography(L,map);
    demo.map_labels.forEach(label=>{const m=L.marker([label.lat,label.lng],{icon:L.divIcon({className:'map-place',html:label.name,iconSize:[80,20]}),interactive:false}).addTo(map);labels.push({el:()=>m.getElement(),ll:[label.lat,label.lng]});});hideNearLabels();
   });
   const portMarker=L.marker(port,{icon:L.divIcon({className:'port-marker',html:'<span>⚑</span>',iconSize:[28,28],iconAnchor:[14,14]}),title:demo.port.name}).addTo(map);
   portMarker.bindTooltip(demo.port.name,{permanent:true,direction:'right',className:'port-tooltip'});
   if(position){L.polyline([position,port],{color:color(stale?'--muted':'--blue'),weight:2,dashArray:'5 7',opacity:stale?.4:.8,interactive:false}).addTo(map);
    L.circle(position,{radius:stale?14000:11000,color:color(stale?'--muted':'--blue'),weight:1,dashArray:stale?'4 5':undefined,fillOpacity:.08}).addTo(map);
    const ship=L.marker(position,{icon:L.divIcon({className:`ship-marker ${stale?'stale':''}`,html:'<span>▲</span>',iconSize:[30,30],iconAnchor:[15,15]}),title:stale?'마지막 수신 위치':'수신 위치',opacity:stale?.45:1}).addTo(map);
    const tip=document.createElement('span');tip.textContent=r.vessel?.name??'선박 수신 위치';ship.bindTooltip(tip,{permanent:true,direction:'bottom',className:'ship-tooltip',offset:[0,16]});
   }
   // 칸 크기가 처음 잡힌 뒤(스크롤바 생김, 칸이 펼쳐짐 등)에도 사용자가 지도를 만지기 전이면 배와 부산항에 다시 맞춘다
   const observer=new ResizeObserver(()=>{map.invalidateSize();if(!touched.current)home();});observer.observe(host.current);cleanup=()=>{observer.disconnect();baseRef.current?.dispose();baseRef.current=null;mapRef.current=null;map.remove();};
  });return()=>{disposed=true;cleanup?.();};
 },[p,r.vessel?.name,stale]);

 /** 지도 펼치기: 지도 칸이 작은 자리에서 작업 공간 전체(상단바 아래, 두 칸 모두)로 커진다. 지도 칸(frame)을 fixed로 바꾼 뒤
  * 원래 자리(slot)의 크기로 되돌려 놓고 transform을 풀어 주는 FLIP 방식이라 레이아웃을 매 프레임 다시 계산하지 않는다. 움직임 줄이기를 켰으면 바로 바뀐다. */
 const reduced=()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches;
 /** 칸 크기가 바뀐 뒤 Leaflet과 MapLibre 캔버스를 새 크기에 맞춘다. 맞추지 않으면 세계 지도 타일이 옛 크기에 머문다 */
 function settle(){mapRef.current?.invalidateSize({animate:false});baseRef.current?.resize();}
 function open(){
  if(big)return;const m=document.querySelector('main')?.getBoundingClientRect();if(!m)return;
  const g=window.innerWidth<=700?8:16,bottom=Math.min(m.bottom,window.innerHeight);
  setBox({bt:m.top,bl:m.left,bw:m.width,bh:bottom-m.top,top:m.top+g,left:m.left+g,width:m.width-2*g,height:bottom-m.top-2*g});setBig(true);
 }
 function close(){
  if(!big||closing.current)return;const f=frame.current,s=slot.current;
  const finish=()=>{closing.current=false;setOut(false);flushSync(()=>setBig(false));toggle.current?.focus();settle();};
  if(!f||!s||reduced()){finish();return;}
  closing.current=true;setOut(true);const to=flip(s.getBoundingClientRect(),f.getBoundingClientRect());
  const a=f.animate([{transform:'none'},{transform:to}],{duration:260,easing:EASE,fill:'forwards'});
  a.onfinish=()=>{finish();a.cancel();};
 }
 useLayoutEffect(()=>{
  const m=mapRef.current;if(m){m.invalidateSize({animate:false});reset.current();m.scrollWheelZoom[big?'enable':'disable']();}
  if(!big)return;toggle.current?.focus();document.body.dataset.mapBig='1';
  const f=frame.current,s=slot.current;if(f&&s&&!reduced())f.animate([{transform:flip(s.getBoundingClientRect(),f.getBoundingClientRect())},{transform:'none'}],{duration:320,easing:EASE});
  // 펼침 애니메이션이 끝난 뒤 한 번 더 맞춘다(타일이 칸을 가득 채우게)
  const t=window.setTimeout(settle,reduced()?0:340);
  return()=>{window.clearTimeout(t);delete document.body.dataset.mapBig;};
 },[big]);
 // 펼친 동안 Esc로 닫는다. 채팅 칸의 "크게 보기"도 같은 길로 연다
 useEffect(()=>{
  const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape'&&big){e.preventDefault();close();}};
  document.addEventListener('keydown',onKey);return()=>document.removeEventListener('keydown',onKey);
 });
 useEffect(()=>{const on=()=>open();window.addEventListener('marvia:map-expand',on);return()=>window.removeEventListener('marvia:map-expand',on);});
 // 펼친 동안 Tab이 지도 밖으로 나가지 않게 가둔다
 function trap(e:React.KeyboardEvent){
  if(e.key!=='Tab'||!big)return;const els=[...(frame.current?.querySelectorAll<HTMLElement>('button,summary,a[href],[tabindex="0"]')??[])].filter(x=>!x.hasAttribute('disabled'));
  if(!els.length)return;const first=els[0],last=els[els.length-1];
  if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
 }
 // 오래된 위치는 문장 대신 "6시간 전 위치" 같은 작은 배지로 알린다 (판단에 영향 주는 주의, 01_공통 작은 글씨 규칙)
 const hrs=p&&stale?Math.floor((Date.now()-new Date(p.last_time).getTime())/3.6e6):0;
 const staleText=Number.isNaN(hrs)||hrs<1?'오래된 위치':hrs>=48?`${Math.floor(hrs/24)}일 전 위치`:`${hrs}시간 전 위치`;
 const distance=r.eta?.distance_nm;
 const fresh=p?.freshness==='fresh'?'수신 정상':stale?staleText:'위치 확인 안 됨';
 return <section id="big-map" tabIndex={-1} className={`map-section ${stale?'map-stale':''}${big?' big':''}`}><h2 className="sr-only">{stale?'마지막 수신 위치':p?'선박과 부산항의 위치':'부산항 기준 지도'}</h2>
  {big&&box&&<div className={`map-backdrop${out?' out':''}`} style={{top:box.bt,left:box.bl,width:box.bw,height:box.bh}} onClick={close} aria-hidden="true"/>}
  <div ref={slot} className="map-slot"><div ref={frame} className={`map-frame${big?' is-overlay':''}`} style={big&&box?{top:box.top,left:box.left,width:box.width,height:box.height}:undefined} role={big?'dialog':undefined} aria-modal={big?true:undefined} aria-label={big?'지도 크게 보기':undefined} onKeyDown={trap}><div ref={host} className="leaflet-host" role="region" aria-label="부산항과 선박 수신 위치 지도"/>
  {/* 왼쪽 위: 판단에 영향 주는 주의는 문장 대신 작은 배지로 (예정일 2곳 다름 등, 01_공통 작은 글씨 규칙). 점선이 실제 항적이 아니라는 안내는 ⓘ 뒤로 접었다 */}
  <div className="map-chips">{!p&&<span className="map-chip">선박 위치가 없어 부산항 기준으로 보여 줘요</span>}{r.conflicts.map((c,i)=><InfoTip key={i} label={`${conflictBadge(c.signals)} 설명`} badge={conflictBadge(c.signals)}><strong>{sourceLabels[c.chosen]??c.chosen} 기준</strong> · {c.why}</InfoTip>)}{p&&<InfoTip label="점선 설명">점선은 대략적인 방향이에요. 실제 항적이 아니에요.</InfoTip>}</div>
  {/* 아이콘 단추: 펼치기(오른쪽 위)와 확대·축소·맞추기(왼쪽 아래). 글자 없이 아이콘만 쓰므로 이름(aria-label)과 툴팁(title)을 단다 */}
  <div className="map-tools">
   <button ref={toggle} type="button" className="map-tool map-expand" aria-pressed={big} aria-label={big?'지도 줄이기':'지도 펼치기'} title={big?'지도 줄이기 (Esc)':'지도 펼치기'} onClick={big?close:open}>{big?<Minimize2 size={18}/>:<Maximize2 size={18}/>}</button>
  </div>
  <div className="map-zoom"><button type="button" className="map-tool" aria-label="지도 확대" title="확대" onClick={()=>{touched.current=true;mapRef.current?.zoomIn();}}><Plus size={18}/></button><button type="button" className="map-tool" aria-label="지도 축소" title="축소" onClick={()=>{touched.current=true;mapRef.current?.zoomOut();}}><Minus size={18}/></button><button type="button" className="map-tool map-reset" onClick={()=>{touched.current=false;reset.current();}} aria-label="선박과 부산항에 지도 맞추기" title="선박과 부산항에 맞추기"><LocateFixed size={18}/></button></div>
 </div></div>
  {/* 지도 아래 한 줄 요약: 판정은 작은 점과 글자로, 선명·거리·수신 상태는 옅은 글씨로 (디자인 방향: 채운 배지·떠 있는 흰 카드 대신) */}
  <div className="map-summary" ref={card}>
   <div className="map-summary-main">{r.verdict&&<span className={`verdict-dot ${r.verdict}`}><i aria-hidden="true"/>{verdictLabels[r.verdict]}</span>}{r.vessel?.name&&<strong className="map-card-ship">{r.customs?.goods_name&&<span className="map-card-goods">{r.customs.goods_name} 실은 </span>}{r.vessel.name}{r.vessel.flag&&<span> ({countryLabel(r.vessel.flag)})</span>}</strong>}</div>
   {watch&&<div className="map-summary-watch">{watch}</div>}
   <div className="map-card-meta">{distance!==null&&distance!==undefined&&<span>부산까지 <b>{distance}</b>해리</span>}<small className={`freshness ${p?.freshness??'unknown'}`}>{fresh}{p&&` · ${dateTime(p.last_time,true)} 기준`}{p&&stale&&' (현재 위치 아님)'}</small></div>
  </div></section>;
}
