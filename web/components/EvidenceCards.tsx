'use client';
/** E5 근거 카드. 펼치면 출처·항목·값·조회 시각을 표로 보여 준다. 원본 JSON과 추적 ID는 사용자 화면에 내지 않는다 (10-02 화면 용어 점검).
 * React 텍스트로만 그려 HTML로 해석되지 않는다. */
import {FileCheck2,Plus} from 'lucide-react';
import type {Evidence} from '@/lib/types';
import {dateTime,fieldLabel,sourceLabels} from '@/lib/format';
import {Empty,SectionTitle} from './Shared';
export function EvidenceCards({evidence}:{evidence:Evidence[];traceId?:string}) {
 return <section id="evidence" className="evidence-section"><SectionTitle label="판단의 근거를 확인하세요" kicker="EVIDENCE, NOT GUESSWORK" side={<span className="subtle-badge">{evidence.length}개 근거</span>}/>{evidence.length?<div className="evidence-grid">{evidence.map((e,i)=><details className="evidence-item" key={`${e.field}-${i}`}><summary><span className="evidence-source"><FileCheck2 size={15}/>{sourceLabels[e.source]??'기타 출처'}</span><span className="evidence-field">{fieldLabel(e.field)}</span><strong>{e.value}</strong><time>{dateTime(e.fetched_at,true)} 조회</time><Plus size={14} className="expand-icon"/></summary><dl className="evidence-detail"><div><dt>출처</dt><dd>{sourceLabels[e.source]??'기타 출처'}</dd></div><div><dt>항목</dt><dd>{fieldLabel(e.field)}</dd></div><div><dt>값</dt><dd>{e.value}</dd></div><div><dt>조회 시각</dt><dd>{dateTime(e.fetched_at)}</dd></div></dl></details>)}</div>:<Empty>확인된 근거가 없습니다. 값을 추정해 채우지 않습니다.</Empty>}</section>;
}
