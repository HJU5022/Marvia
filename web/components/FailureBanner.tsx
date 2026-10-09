'use client';
/** partial/failed/unsupported use distinct wording and recoveries. No fake retry counts.
 * 지원 범위 밖은 B/L·양륙항을 고쳐 다시 묻도록 AI 입력창으로 돌려보낸다 (예전 #bl 입력칸은 ChatBar로 바뀌어 없다). */
import {CircleHelp,RefreshCw,ShieldAlert,MapPinOff} from 'lucide-react';
import type {AgentResponse} from '@/lib/types';
import {dateTime,statusLabels} from '@/lib/format';
import {focusComposer} from '@/lib/composer';
export function FailureBanner({response:r,onRetry,busy,onMof}:{response:AgentResponse;onRetry:()=>void;busy:boolean;onMof?:()=>void}) {
 if(r.status==='ok'||r.status==='insufficient')return null;
 const unsupported=r.status==='unsupported',Icon=unsupported?MapPinOff:r.status==='failed'?ShieldAlert:CircleHelp;
 return <section className={`failure-banner ${r.status}`} role="status"><div className="failure-icon"><Icon size={27} strokeWidth={1.5}/></div><div className="failure-copy"><span className="eyebrow">{statusLabels[r.status]}</span><h2>{unsupported?'지금은 부산항 화물만 지원해요.':r.status==='failed'?'이번 조회를 완료하지 못했어요.':'일부 정보만 확인했어요.'}</h2><p>{r.answer}</p>{r.position&&<small>마지막으로 받은 시각 {dateTime(r.position.last_time)}{r.position.freshness==='stale'?' (현재 위치가 아니에요)':''}</small>}<div className="button-row">{!unsupported&&<button className="button secondary" onClick={onRetry} disabled={busy}><RefreshCw size={15}/>다시 조회하기</button>}{onMof&&r.evidence.some(e=>e.source==='mof')&&<button className="button text-button" onClick={onMof}>해수부 근거만 보기 <span>↗</span></button>}{unsupported&&<button type="button" className="button secondary" onClick={()=>focusComposer()}>질문 고치기</button>}</div></div></section>;
}
