'use client';
/** 답 문장 속 근거 표시를 작은 칩으로 그리고, 누르면 그 자리에서 작은 말풍선(popover)을 연다.
 * 왜: 오른쪽 패널로 시선을 옮기지 않고 "이 말이 어디서 왔나"를 바로 본다. 표시 검증은 서버가 끝냈다(services/citations.py).
 * 화면은 서버가 준 citations 위치를 믿되, 위치가 글자와 어긋나면 [E#]를 다시 찾는다.
 * 표시가 하나도 없으면(fallback) 글은 그대로 두고 끝에 근거 칩 줄을 모은다.
 * 한 문장에 표시가 여럿이면 하나의 칩으로 합친다("해수부 외 2"). 누르면 말풍선 꼬리 없는 네모 상자가 열리고 출처마다 한 칸씩 보인다.
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

/** 칩 이름: 첫 근거의 출처 이름, 근거가 둘 이상이면 "외 N" (제품 담당 결정) */
function groupLabel(items: EvidenceItem[]) {
  const first = citationSourceLabel(items[0].source);
  return items.length > 1 ? `${first} 외 ${items.length - 1}` : first;
}

/** 한 문장의 근거 묶음 하나를 칩 한 개와 네모 상자로 그린다 */
function Mention({items, label, open, onToggle, popId}: {items: EvidenceItem[]; label: string; open: boolean; onToggle: (el: HTMLButtonElement | null) => void; popId: string}) {
  const ref = useRef<HTMLButtonElement>(null);
  return <span className="ev-wrap">
    <button type="button" ref={ref} className={`ev-chip${open ? ' open' : ''}`} aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? popId : undefined}
      aria-label={`근거 보기: ${label}`} onClick={() => onToggle(ref.current)}>{label}</button>
    {open && <span id={popId} role="dialog" aria-label="근거" className="ev-pop">{items.map(item => <section key={item.id} className="ev-pop-item"><EvidenceBody item={item}/></section>)}</span>}
  </span>;
}

type Part = {t: string} | {g: EvidenceItem[]};

/** 글 조각과 표시를 한 줄로 늘어놓고, 붙어 있는(공백만 사이에 둔) 표시는 한 묶음으로 합친다. 목록에 없는 표시는 버린다 */
function build(text: string, citations: Citation[], byId: Map<string, EvidenceItem>): Part[] {
  const out: Part[] = [];
  let pendingSpace = '';
  for (const p of split(text, citations)) {
    if ('t' in p) {
      const last = out[out.length - 1];
      if (last && 'g' in last && /^\s*$/.test(p.t)) { pendingSpace += p.t; continue; }  // 표시 사이 공백은 합칠 때 버린다
      if (pendingSpace) out.push({t: pendingSpace}), pendingSpace = '';
      out.push(p);
      continue;
    }
    const item = byId.get(p.c.evidence_ref.toUpperCase());
    if (!item) continue;
    const last = out[out.length - 1];
    if (last && 'g' in last) { if (!last.g.includes(item)) last.g.push(item); pendingSpace = ''; }
    else { if (pendingSpace) out.push({t: pendingSpace}), pendingSpace = ''; out.push({g: [item]}); }
  }
  if (pendingSpace) out.push({t: pendingSpace});
  return out;
}

/** renderText: 글자 조각을 그리는 함수. 채팅 말풍선이 웹 링크 바꾸기(linkify)를 넘겨 쓴다. 없으면 글자 그대로 */
export function EvidencePopover({text, citations, evidence, renderText}: {text: string; citations: Citation[]; evidence: EvidenceItem[]; renderText?: (s: string) => ReactNode}) {
  const plain = (s: string): ReactNode => renderText ? renderText(s) : s;
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

  const parts = build(text, citations, byId);
  const toggle = (key: string) => (el: HTMLButtonElement | null) => { opener.current = el; setOpenKey(k => k === key ? null : key); };

  // 서버가 남긴 유효한 표시가 없으면 답 끝에 칩 하나를 둔다. 누르면 모든 근거가 한 상자에 열린다 (제품 담당 결정)
  // 이름이 "근거 1"이면 위쪽 "근거 28개" 버튼과 헷갈렸다. 문장 속 칩처럼 출처 이름("해수부", "해수부 외 1")으로 쓴다
  if (!parts.some(p => 'g' in p)) {
    const cleaned = text.replace(MARK, '').replace(/\s+([.,!?])/g, '$1');
    return <span ref={root} className="ev-text">{plain(cleaned)}
      {evidence.length > 0 && <Mention items={evidence} label={groupLabel(evidence)} open={openKey === 'all'} onToggle={toggle('all')} popId={`${base}-all`}/>}
    </span>;
  }
  return <span ref={root} className="ev-text">{parts.map((p, i) => {
    if ('t' in p) return <span key={i}>{plain(p.t)}</span>;
    const key = `g${i}`;
    return <Mention key={key} items={p.g} label={groupLabel(p.g)} open={openKey === key} onToggle={toggle(key)} popId={`${base}-${i}`}/>;
  })}</span>;
}
