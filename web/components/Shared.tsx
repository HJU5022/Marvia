/** Small display primitives keep status and verdict semantically distinct. */
import {Check, CircleHelp, Eye, OctagonAlert} from 'lucide-react';
import type {Verdict} from '@/lib/types';
import {verdictLabels} from '@/lib/format';
export function VerdictBadge({verdict}:{verdict:Verdict|null}) {const Icon=verdict==='fine'?Check:verdict==='watch'?Eye:verdict==='act'?OctagonAlert:CircleHelp;return <span className={`verdict-badge ${verdict??'neutral'}`}><Icon size={14}/>{verdict?verdictLabels[verdict]:'판정 없음'}</span>;}
export function SectionTitle({label,kicker,side}:{label:string;kicker?:string;side?:React.ReactNode}){return <div className="section-heading"><div>{kicker&&<span className="eyebrow">{kicker}</span>}<h2>{label}</h2></div>{side}</div>;}
export function Empty({children}:{children:React.ReactNode}){return <div className="empty-inline"><CircleHelp size={18}/><span>{children}</span></div>;}
