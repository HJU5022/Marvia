'use client';
/** 대화 맨 위 "근거 N개" 버튼과 그 대화의 근거 모음 패널.
 * 이 대화의 답에 나온 근거를 출처별로 묶고 최신순으로 보여 준다. 같은 출처·항목·값은 한 번만 나온다.
 * 패널은 기존 Drawer(포커스 트랩, Esc, 뒤 화면 inert)를 그대로 쓴다. 글은 React 텍스트라 HTML로 해석되지 않는다. */
import {useMemo, useState} from 'react';
import {FileCheck2} from 'lucide-react';
import {Drawer} from './Drawer';
import {fieldLabel, evidenceValue, dateTime} from '@/lib/format';
import {citationSourceLabel, type ConversationEvidenceEntry} from '@/lib/evidenceTypes';

interface Row {field: string; value: string; fetched_at: string; url?: string; title?: string; order: number}

/** 항목 단위로 펼치고 (출처, 항목, 값)이 같으면 가장 최근 조회 하나만 남긴다. 출처 안에서 최신순 */
export function groupEvidence(entries: ConversationEvidenceEntry[]): {source: string; rows: Row[]}[] {
  const seen = new Map<string, Row & {source: string}>();
  entries.forEach((e, idx) => {
    const order = (e.turn ?? idx) * 1000 + idx % 1000;
    const vals = e.values.length ? e.values : [{field: e.source === 'web' ? 'web' : '', value: ''}];
    for (const v of vals) {
      const key = `${e.source}|${v.field}|${v.value}|${e.url ?? ''}`;
      const prev = seen.get(key);
      if (!prev || order > prev.order) seen.set(key, {source: e.source, field: v.field, value: v.value, fetched_at: e.fetched_at, url: e.url, title: e.title, order});
    }
  });
  const bySource = new Map<string, Row[]>();
  for (const r of seen.values()) bySource.set(r.source, [...(bySource.get(r.source) ?? []), r]);
  return [...bySource.entries()]
    .map(([source, rows]) => ({source, rows: rows.sort((a, b) => b.order - a.order)}))
    .sort((a, b) => b.rows[0].order - a.rows[0].order);
}

export function ConversationEvidence({evidence}: {evidence: ConversationEvidenceEntry[]}) {
  const [open, setOpen] = useState(false);
  const groups = useMemo(() => groupEvidence(evidence), [evidence]);
  const count = groups.reduce((n, g) => n + g.rows.length, 0);
  if (!count) return null;  // 아직 근거가 없으면 버튼을 내지 않는다
  return <>
    <button type="button" className="ev-collect-btn" onClick={() => setOpen(true)} aria-haspopup="dialog"><FileCheck2 size={15}/>근거 {count}개</button>
    {open && <Drawer title="이 대화의 근거 모음" description="이 대화의 답에 나온 근거예요. 최근 것이 위에 있어요." onClose={() => setOpen(false)}>
      <div className="ev-collect">{groups.map(g => <section key={g.source} className="ev-collect-group">
        <h3>{citationSourceLabel(g.source)}<span>{g.rows.length}개</span></h3>
        <ul>{g.rows.map((r, i) => <li key={`${r.field}-${i}`}>
          <span className="ev-collect-field">{g.source === 'web' ? (r.title || '웹') : fieldLabel(r.field)}</span>
          <strong>{r.value ? evidenceValue(r.field, r.value) : '확인 안 됨'}</strong>
          <time>{r.fetched_at ? `${dateTime(r.fetched_at)} 조회` : ''}</time>
          {r.url && <a href={r.url} target="_blank" rel="noopener noreferrer">원문 보기</a>}
        </li>)}</ul>
      </section>)}</div>
    </Drawer>}
  </>;
}
