/** Small display primitives keep status and verdict semantically distinct. */
import {Check, CircleHelp, Eye, OctagonAlert} from 'lucide-react';
import type {Verdict} from '@/lib/types';
import {verdictLabels} from '@/lib/format';
/** 판정 배지. 신호등 색(순항·주의·긴급)은 이 배지와 판정 줄에만 쓴다 (globals.css .verdict-badge, --grade-*).
 * size="lg"는 판정 카드·지도 위 카드처럼 크게 보일 자리용이다. 기본은 표·목록 크기. 글자와 아이콘을 늘 같이 써서 색만으로 구분하지 않는다. */
export function VerdictBadge({verdict,size='md'}:{verdict:Verdict|null;size?:'md'|'lg'}) {const Icon=verdict==='fine'?Check:verdict==='watch'?Eye:verdict==='act'?OctagonAlert:CircleHelp;return <span className={`verdict-badge ${verdict??'neutral'}${size==='lg'?' lg':''}`}><Icon size={size==='lg'?20:16}/>{verdict?verdictLabels[verdict]:'판정 없음'}</span>;}
export function SectionTitle({label,kicker,side}:{label:string;kicker?:string;side?:React.ReactNode}){return <div className="section-heading"><div>{kicker&&<span className="eyebrow">{kicker}</span>}<h2>{label}</h2></div>{side}</div>;}
export function Empty({children}:{children:React.ReactNode}){return <div className="empty-inline"><CircleHelp size={18}/><span>{children}</span></div>;}
