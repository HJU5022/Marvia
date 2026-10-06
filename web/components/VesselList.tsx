'use client';
/** 입항 예정 선박 검색 결과 (docs/specs/chat-search.md vessel_search). Manus 2-4 시안으로 다시 짬:
 * 위에 제목·건수·"모든 선종 보기", 가운데 10칸 표, 표 아래에 척수와 페이지 넘김, 맨 아래에 고른 배의 자세히 카드를 붙여 둔다.
 * 해수부 입항 신고 기준이라 "직전 기항지"를 그대로 보여 준다. 출발지가 아니라는 점을 표 아래에 밝힌다 (EC-04). 판정은 하지 않는다.
 * 자세히는 예전처럼 따로 뜨는 창이 아니라 표 바로 아래에 붙는다(시안). 처음엔 첫 줄 배를 보이고, 줄이나 선명을 누르면 그 배로 바뀐다.
 * 수십 척이 나올 수 있어 화면에서 페이지로 나눈다. 한 페이지 10·30·50척 중 고른다(기본 10).
 * 시안의 "질문: ..." 줄은 이 화면이 사용자 질문 글을 받지 않아 넣지 않는다.
 */
import {useEffect, useMemo, useRef, useState} from 'react';
import {ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Info, Ship, SlidersHorizontal} from 'lucide-react';
import {VesselDetail} from './VesselDetail';
import {dateTime, placeLabel} from '@/lib/format';
import type {ChatResponse, VesselItem} from '@/lib/types';

const PAGE_SIZES = [10, 30, 50] as const;

/** 정렬할 수 있는 칸. 머리글 순서와 같다. 시각 칸은 ISO 문자열이라 글자 순서가 곧 시간 순서다 */
const COLUMNS: {key: keyof VesselItem; label: string}[] = [
  {key: 'ship_name', label: '선박 이름'}, {key: 'call_sign', label: '호출부호'}, {key: 'nationality', label: '국적'},
  {key: 'ship_kind', label: '선박 종류'}, {key: 'previous_port', label: '직전에 들른 항구'}, {key: 'expected_arrival', label: '부산 입항 예정'},
  {key: 'planned_departure', label: '부산 출항 예정'}, {key: 'next_port', label: '다음에 들를 항구'}, {key: 'facility', label: '접안 예정'},
  {key: 'purpose', label: '목적'},
];

/** 표 칸의 빈 값은 "확인되지 않음" 대신 줄표로 (좁은 칸, 시안) */
const cell = (x: string | null | undefined) => x ? x : '-';
const when = (x: string | null | undefined) => x ? dateTime(x, true) : '-';

export function VesselList({data}: {data: ChatResponse}) {
  const [size, setSize] = useState<number>(PAGE_SIZES[0]);
  const [page, setPage] = useState(1);
  // 자세히 보는 배. 한 번에 하나만 보이고, 고르지 않았으면 표의 첫 줄 배가 보인다
  const [open, setOpen] = useState<VesselItem | null>(null);
  const detailRef = useRef<HTMLDivElement>(null);
  // 기본은 수입 화물선만. 서버가 배마다 is_cargo를 붙여 보낸다(기준 목록은 skills/port-busan/cargo-vessels.md)
  const [allKinds, setAllKinds] = useState(false);
  // 기본은 서버가 준 순서(부산 입항 예정 빠른 순)
  const [sort, setSort] = useState<{key: keyof VesselItem; dir: 'asc' | 'desc'} | null>(null);
  // 새 검색 결과가 오면 첫 페이지, 정렬 처음으로
  useEffect(() => { setPage(1); setSort(null); setOpen(null); setAllKinds(false); }, [data]);

  const sorted = useMemo(() => {
    const base = allKinds ? data.vessels : data.vessels.filter(v => v.is_cargo !== false);
    if (!sort) return base;
    const sign = sort.dir === 'asc' ? 1 : -1;
    return [...base].sort((a, b) => {
      const x = a[sort.key], y = b[sort.key];
      if (x == null || x === '') return y == null || y === '' ? 0 : 1;  // 빈 값은 방향과 상관없이 뒤로
      if (y == null || y === '') return -1;
      return sign * String(x).localeCompare(String(y), 'ko', {numeric: true});
    });
  }, [data.vessels, sort, allKinds]);
  const cargoCount = data.vessels.filter(v => v.is_cargo !== false).length;
  function toggle(key: keyof VesselItem) {
    setSort(s => s?.key === key ? (s.dir === 'asc' ? {key, dir: 'desc'} : null) : {key, dir: 'asc'});
    setPage(1);
  }
  function pick(v: VesselItem) {
    setOpen(v);
    // 표가 길어 자세히 카드가 화면 밖일 수 있어, 눌렀을 때만 그쪽으로 살짝 내린다
    requestAnimationFrame(() => detailRef.current?.scrollIntoView({block: 'nearest', behavior: 'smooth'}));
  }

  const total = sorted.length;
  const pages = Math.max(1, Math.ceil(total / size));
  const current = Math.min(page, pages);
  const start = (current - 1) * size;
  const rows = sorted.slice(start, start + size);
  const selected = open && sorted.includes(open) ? open : sorted[0] ?? null;
  // 페이지 번호는 지금 페이지 앞뒤 2개까지만 보여 준다
  const numbers = Array.from({length: pages}, (_, i) => i + 1).filter(n => Math.abs(n - current) <= 2 || n === 1 || n === pages);

  return <section className="history-panel vessel-results vl" aria-label="입항 예정 선박">
    <header className="vl-head">
      <div>
        <h2>{data.place ? `${placeLabel(data.place)}에서 들른 배` : '부산 입항 예정 배'}</h2>
        <p>{total}척 · {data.days ?? 7}일{data.ports.length > 0 && <> · 직전 기항지 {data.ports.join(', ')}</>} · 모든 시각 한국 시간</p>
      </div>
      <button type="button" className="vl-kinds-toggle" aria-pressed={allKinds}
        onClick={() => { setAllKinds(v => !v); setPage(1); setOpen(null); }}><SlidersHorizontal size={16} strokeWidth={1.75}/>{allKinds ? '수입 화물선만 보기' : '모든 선박 종류 보기'}</button>
    </header>
    {total ? <>
      <div className="table-scroll vl-table" role="region" aria-label="입항 예정 선박 표" tabIndex={0}><table>
        <thead><tr>{COLUMNS.map(c => {
          const on = sort?.key === c.key;
          const Icon = on ? (sort!.dir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown;
          return <th key={c.key} aria-sort={on ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
            <button type="button" className={`sort-head ${on ? 'on' : ''}`} onClick={() => toggle(c.key)}>{c.label}<Icon size={14}/></button></th>;
        })}</tr></thead>
        <tbody>{rows.map((v, i) => <tr key={`${v.call_sign ?? ''}|${v.ship_name}-${start + i}`} className={selected === v ? 'row-open' : ''} onClick={() => pick(v)}>
          <td><button type="button" className="ship-link" onClick={e => { e.stopPropagation(); pick(v); }} aria-pressed={selected === v}>{v.ship_name}</button></td><td>{cell(v.call_sign)}</td>
          <td>{cell(v.nationality)}</td><td>{cell(v.ship_kind)}</td>
          <td>{cell(v.previous_port)}</td>
          <td>{when(v.expected_arrival)}</td><td>{when(v.planned_departure)}</td>
          <td>{cell(v.next_port)}</td><td>{cell(v.facility)}</td><td>{cell(v.purpose)}</td>
        </tr>)}</tbody></table></div>
      <div className="vl-foot">
        <span className="vl-kinds">수입 화물선 {cargoCount}척 · 전체 {data.vessels.length}척</span>
        <nav className="pager" aria-label="선박 표 페이지">
          <span className="pager-range">{start + 1}-{Math.min(start + size, total)} / {total}</span>
          <label className="pager-size">한 페이지
            <select value={size} onChange={e => { setSize(Number(e.target.value)); setPage(1); }} aria-label="한 페이지에 볼 선박 수">
              {PAGE_SIZES.map(n => <option key={n} value={n}>{n}개씩 보기</option>)}
            </select></label>
          <div className="pager-buttons">
            <button type="button" className="icon-button" onClick={() => setPage(current - 1)} disabled={current <= 1} aria-label="이전 페이지"><ChevronLeft size={16}/></button>
            {numbers.map((n, i) => <span key={n} className="pager-num-wrap">
              {i > 0 && n - numbers[i - 1] > 1 && <span className="pager-gap">…</span>}
              <button type="button" className={`pager-num ${n === current ? 'active' : ''}`} onClick={() => setPage(n)} aria-current={n === current ? 'page' : undefined}>{n}</button>
            </span>)}
            <button type="button" className="icon-button" onClick={() => setPage(current + 1)} disabled={current >= pages} aria-label="다음 페이지"><ChevronRight size={16}/></button>
          </div>
        </nav>
      </div>
    </> : <div className="empty-state vl-empty"><Ship/><h3>{!allKinds && data.vessels.length ? '수입 화물선이 없어요.' : '조건에 맞는 입항 예정 선박이 없어요.'}</h3><p>{!allKinds && data.vessels.length ? `모든 선박 종류 보기를 켜면 ${data.vessels.length}척이 보여요.` : data.reply}</p></div>}
    <p className="vl-notes"><Info size={14} strokeWidth={1.75} aria-hidden="true"/>출처: 해양수산부 선박운항정보(입항 신고). 직전에 들른 항구 기준이고, 처음 출발한 항구와 시각은 신고에 없어요. 내 화물은 B/L 번호로 조회해 주세요.</p>
    {selected && <div ref={detailRef}><VesselDetail vessel={selected}/></div>}
  </section>;
}
