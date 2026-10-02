'use client';
/** E5 expands exact source/field/value/time. React text prevents HTML interpretation. */
import {FileCheck2,Plus} from 'lucide-react';
import type {Evidence} from '@/lib/types';
import {dateTime,sourceLabels} from '@/lib/format';
import {Empty,SectionTitle} from './Shared';
export function EvidenceCards({evidence,traceId}:{evidence:Evidence[];traceId:string}) {
 return <section id="evidence" className="evidence-section"><SectionTitle label="판단의 근거를 확인하세요" kicker="EVIDENCE, NOT GUESSWORK" side={<span className="subtle-badge">{evidence.length}개 근거</span>}/>{evidence.length?<div className="evidence-grid">{evidence.map((e,i)=><details className="evidence-item" key={`${e.field}-${i}`}><summary><span className="evidence-source"><FileCheck2 size={15}/>{sourceLabels[e.source]}</span><span className="evidence-field mono">{e.field}</span><strong>{e.value}</strong><time>{dateTime(e.fetched_at,true)} 조회</time><Plus size={14} className="expand-icon"/></summary><pre>{JSON.stringify(e,null,2)}</pre></details>)}</div>:<Empty>확인된 근거가 없습니다. 값을 추정해 채우지 않습니다.</Empty>}<div className="trace-line"><span>요청 추적 ID</span><code>{traceId||'확인되지 않음'}</code><span>트레이스 URL 미제공</span></div></section>;
}
