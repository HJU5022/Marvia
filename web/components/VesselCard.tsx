/** Every VesselInfo/Position field remains visible, including null identifiers. E4.
 * "펼쳐 보기" 안의 원자료 칸이라 작게: 선명 한 줄 + 값 표. 시안에 따로 없는 화면이라 선박 자세히 카드(VesselDetail)와 같은 말투로 맞췄다. */
import {Ship} from 'lucide-react';
import type {AgentResponse} from '@/lib/types';
import {countryLabel,dateTime,navStatusLabel,shipTypeLabel,shown} from '@/lib/format';
import {Empty,SectionTitle} from './Shared';
export function VesselCard({response:r}:{response:AgentResponse}) {
 const v=r.vessel,p=r.position;const candidate=r.vessel_match==='confirmed'&&r.vessel_candidates.length===1?r.vessel_candidates[0]:null;
 return <section className="vessel-section vc"><SectionTitle label="내 화물의 선박" kicker="선박 확인" side={<span className="subtle-badge">{r.vessel_match==='confirmed'?'선박 확인됨':r.vessel_match==='uncertain'?'선박 확인 필요':'선박 못 찾음'}</span>}/>
  {v||candidate?<>
   <div className="vessel-name vc-name"><span className="vessel-mark"><Ship size={24} strokeWidth={1.6}/></span><div><h3>{v?.name??candidate?.name}</h3><p>{countryLabel(v?.flag??candidate?.flag)} 국적 · <abbr title="MMSI: 선박마다 붙는 9자리 무선 식별 번호">선박 식별 번호</abbr> <b className="mono">{shown(v?.mmsi??candidate?.mmsi)}</b></p></div></div>
   <dl className="vessel-details vc-grid">{[['IMO 번호(선박 등록 번호)',v?.imo??candidate?.imo],['호출부호(무선 이름)',v?.call_sign],['선박 종류',shipTypeLabel(v?.ship_type??candidate?.ship_type)],['항차 번호',v?.voyage_no]].map(([k,x])=><div key={String(k)}><dt>{k}</dt><dd>{shown(x)}</dd></div>)}</dl></>
  :<Empty>선박 상세 정보가 없어요.</Empty>}
  {p&&<>
   <div className={`position-strip vc-strip ${p.freshness}`}><span>{p.freshness==='fresh'?'받은 위치':p.freshness==='stale'?'마지막으로 받은 위치 (오래됨)':'받은 위치 (받은 시각 확인 안 됨)'}</span><time>{dateTime(p.last_time)}</time></div>
   <dl className="position-details vc-grid"><div><dt>좌표</dt><dd>{p.lat.toFixed(2)} N / {p.lng.toFixed(2)} E</dd></div><div><dt>속력과 진행 방향</dt><dd>{p.sog}노트(약 {Math.round(p.sog*1.852)}km/h) / {p.cog}°</dd></div><div><dt>항해 상태</dt><dd>{navStatusLabel(p.navistat)}</dd></div><div><dt>남은 거리 {p.freshness==='stale'?'(수신 당시)':''}</dt><dd>{r.eta?.distance_nm===null||r.eta?.distance_nm===undefined?'확인 안 됨':`${r.eta.distance_nm} 해리`}</dd></div></dl></>}
 </section>;
}
