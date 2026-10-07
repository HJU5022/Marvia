'use client';
/** 답 문장 속 근거 표시를 작은 칩으로 그리고, 누르면 그 자리에서 작은 말풍선(popover)을 연다 (10-08 정운 실사용 58번).
 * 왜: 오른쪽 패널로 시선을 옮기지 않고 "이 말이 어디서 왔나"를 바로 본다. 표시 검증은 서버가 끝냈다(services/citations.py).
 * 화면은 서버가 준 citations 위치를 믿되, 위치가 글자와 어긋나면 [E#]를 다시 찾는다.
 * 표시가 하나도 없으면(fallback) 글은 그대로 두고 끝에 근거 칩 줄을 모은다.
 * 접근성: 칩은 button(aria-expanded/haspopup), Esc와 바깥 클릭으로 닫고 닫으면 칩으로 포커스가 돌아간다. 글은 React 텍스트로만 그려 HTML로 해석되지 않는다. */
import {useCallback, useEffect, useId, useRef, useState, type ReactNode} from 'react';
import {fieldLabel, evidenceValue, dateTime} from '@/lib/format';
import {citationSourceLabel, type Citation, type EvidenceItem} from '@/lib/evidenceTypes';

const MARK = /\[E\d+\]/gi;

/** 글을 [글자 조각 | 표시] 순서로 나눈다. 서버 위치가 맞으면 그것을, 아니면 정규식으로 찾는다 */
function split(text: string, citations: Citation[]): ({t: string} | {c: Citation})[] {
  const exact = citations.length > 0 && citations.every(c => text.slice(c.start, c.end).toUpperCase() === `[${c.evidence_ref.toUpperCase()}]`);
  const marks: Citation[] = exact ? [...citations].sort((a, b) => a.start - b.start)
    : [...text.matchAll(MARK)].map((m, i) => ({id: `r${i}`, start: m.index ?? 0, end: (m.index ?? 0) + m[0].length, evidence_ref: m[0].slice(1, -1).toUpperCase()}));
  const parts: ({t: string} | {c: Citation})[] = [];
  let at = 0;
  for (const c of marks) {
    if (c.start > at) parts.push({t: text.slice(at, c.start)});
    parts.push({c});
    at = c.end;
  }
  if (at < text.length) parts.push({t: text.slice(at)});
  return parts;
}

function EvidenceBody({item}: {item: EvidenceItem}) {
  return <>
    <div className="ev-pop-head"><strong>{citationSourceLabel(item.source)}</strong><time>{item.fetched_at ? `${dateTime(item.fetched_at)} 조회` : '조회 시각 확인 안 됨'}</time></div>
    <dl className="ev-pop-values">{item.values.map((v, i) => <div key={`${v.field}-${i}`}>
      <dt>{item.source === 'web' ? '발췌' : fieldLabel(v.field)}</dt><dd>{evidenceValue(v.field, v.value)}</dd></div>)}</dl>
    {item.url && <a className="ev-pop-link" href={item.url} target="_blank" rel="noopener noreferrer">{item.title || '원문 보기'}</a>}
  </>;
}

function Chip({item, label, open, onToggle, popId}: {item: EvidenceItem; label: ReactNode; open: boolean; onToggle: (el: HTMLButtonElement | null) => void; popId: string}) {
  const ref = useRef<HTMLButtonElement>(null);
  return <span className="ev-wrap">
    <button type="button" ref={ref} className={`ev-chip${open ? ' open' : ''}`} aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? popId : undefined}
      aria-label={`근거 보기: ${citationSourceLabel(item.source)}`} onClick={() => onToggle(ref.current)}>{label}</button>
    {open && <span id={popId} role="dialog" aria-label={`${citationSourceLabel(item.source)} 근거`} className="ev-pop"><EvidenceBody item={item}/></span>}
  </span>;
}

export function EvidencePopover({text, citations, evidence}: {text: string; citations: Citation[]; evidence: EvidenceItem[]}) {
  const base = useId();
  const [openKey, setOpenKey] = useState<string | null>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const root = useRef<HTMLSpanElement>(null);
  const byId = new Map(evidence.map(e => [e.id.toUpperCase(), e]));
  const close = useCallback((restore: boolean) => {
    setOpenKey(null);
    if (restore) opener.current?.focus();
  }, []);

  useEffect(() => {
    if (!openKey) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); close(true); } };
    const onDown = (e: MouseEvent) => { if (root.current && !root.current.contains(e.target as Node)) close(false); };
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('mousedown', onDown);
    return () => { document.removeEventListener('keydown', onKey, true); document.removeEventListener('mousedown', onDown); };
  }, [openKey, close]);

  const parts = split(text, citations);
  const used = parts.filter((p): p is {c: Citation} => 'c' in p && byId.has(p.c.evidence_ref.toUpperCase()));
  const toggle = (key: string) => (el: HTMLButtonElement | null) => { opener.current = el; setOpenKey(k => k === key ? null : key); };

  // 서버가 남긴 유효한 표시가 없으면 글 끝에 근거 칩을 모은다 (결정 2)
  if (!used.length) {
    const cleaned = text.replace(MARK, '').replace(/\s+([.,!?])/g, '$1');
    return <span ref={root} className="ev-text">{cleaned}
      {evidence.length > 0 && <span className="ev-fallback" aria-label="이 답의 근거">{evidence.map(e =>
        <Chip key={e.id} item={e} label={citationSourceLabel(e.source)} open={openKey === e.id} onToggle={toggle(e.id)} popId={`${base}-${e.id}`}/>)}</span>}
    </span>;
  }
  return <span ref={root} className="ev-text">{parts.map((p, i) => {
    if ('t' in p) return <span key={i}>{p.t}</span>;
    const item = byId.get(p.c.evidence_ref.toUpperCase());
    if (!item) return null;  // 목록에 없는 표시는 글자로 내지 않는다
    const key = `${p.c.id}-${i}`;
    return <Chip key={key} item={item} label={citationSourceLabel(item.source)} open={openKey === key} onToggle={toggle(key)} popId={`${base}-${i}`}/>;
  })}</span>;
}
