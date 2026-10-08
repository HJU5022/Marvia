'use client';
/** E5 근거 카드. 펼치면 출처·항목·값·조회 시각을 표로 보여 준다. 원본 JSON과 추적 ID는 사용자 화면에 내지 않는다.
 * 값은 evidenceValue로 시각·단위만 읽기 좋게 바꾼다 (UI 점검 F14). React 텍스트로만 그려 HTML로 해석되지 않는다. */
import {FileCheck2,Plus} from 'lucide-react';
import type {Evidence} from '@/lib/types';
import {dateTime,evidenceValue,fieldLabel,sourceLabels} from '@/lib/format';
import {Empty} from './Shared';
export function EvidenceCards({evidence}:{evidence:Evidence[];traceId?:string}) {
 return <section id="evidence" className="evidence-section"><div className="fold-subhead"><h3 className="fold-sub">판단의 근거를 확인해 보세요</h3><span className="subtle-badge">{evidence.length}개 근거</span></div>{evidence.length?<div className="evidence-grid">{evidence.map((e,i)=><details className="evidence-item" key={`${e.field}-${i}`}><summary><span className="evidence-source"><FileCheck2 size={15}/>{sourceLabels[e.source]??'기타 출처'}</span><span className="evidence-field">{fieldLabel(e.field)}</span><strong>{evidenceValue(e.field,e.value)}</strong><time>{dateTime(e.fetched_at,true)} 조회</time><Plus size={14} className="expand-icon"/></summary><dl className="evidence-detail"><div><dt>출처</dt><dd>{sourceLabels[e.source]??'기타 출처'}</dd></div><div><dt>항목</dt><dd>{fieldLabel(e.field)}</dd></div><div><dt>값</dt><dd>{evidenceValue(e.field,e.value)}</dd></div><div><dt>조회 시각</dt><dd>{dateTime(e.fetched_at)}</dd></div></dl></details>)}</div>:<Empty>확인된 근거가 없어요. 값을 짐작해서 채우지 않아요.</Empty>}</section>;
}
