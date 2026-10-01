'use client';
/** 입항 예정 선박 검색 결과 (docs/specs/chat-search.md vessel_search). 해수부 입항 신고 기준이라 "직전 기항지"를 그대로 보여 준다.
 * 출발지가 아니라는 점을 표 위에 밝힌다 (EC-04). 판정은 하지 않는다. 내 화물이면 B/L로 다시 물어보게 안내한다.
 * 수십 척이 나올 수 있어 화면에서 페이지로 나눈다. 한 페이지 10·30·50척 중 고른다(기본 10).
 */
import {useEffect, useMemo, useState} from 'react';
import {Anchor, ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Ship} from 'lucide-react';
import {SectionTitle} from './Shared';
import {dateTime, shown} from '@/lib/format';
import type {ChatResponse, VesselItem} from '@/lib/types';

const PAGE_SIZES = [10, 30, 50] as const;

/** 정렬할 수 있는 칸. 머리글 순서와 같다. 시각 칸은 ISO 문자열이라 글자 순서가 곧 시간 순서다 */
const COLUMNS: {key: keyof VesselItem; label: string}[] = [
  {key: 'ship_name', label: '선명'}, {key: 'call_sign', label: '호출부호'}, {key: 'nationality', label: '국적'},
  {key: 'ship_kind', label: '선종'}, {key: 'previous_port', label: '직전 기항지'}, {key: 'expected_arrival', label: '부산 입항 예정'},
  {key: 'planned_departure', label: '부산 출항 예정'}, {key: 'next_port', label: '다음 기항지'}, {key: 'facility', label: '접안 예정'},
  {key: 'purpose', label: '목적'},
];

export function VesselList({data}: {data: ChatResponse}) {
  const [size, setSize] = useState<number>(PAGE_SIZES[0]);
  const [page, setPage] = useState(1);
  // 기본은 서버가 준 순서(부산 입항 예정 빠른 순)
  const [sort, setSort] = useState<{key: keyof VesselItem; dir: 'asc' | 'desc'} | null>(null);
  // 새 검색 결과가 오면 첫 페이지, 정렬 처음으로
  useEffect(() => { setPage(1); setSort(null); }, [data]);

  const sorted = useMemo(() => {
    if (!sort) return data.vessels;
    const sign = sort.dir === 'asc' ? 1 : -1;
    return [...data.vessels].sort((a, b) => {
      const x = a[sort.key], y = b[sort.key];
      if (x == null || x === '') return y == null || y === '' ? 0 : 1;  // 빈 값은 방향과 상관없이 뒤로
      if (y == null || y === '') return -1;
      return sign * String(x).localeCompare(String(y), 'ko', {numeric: true});
    });
  }, [data.vessels, sort]);
  function toggle(key: keyof VesselItem) {
    setSort(s => s?.key === key ? (s.dir === 'asc' ? {key, dir: 'desc'} : null) : {key, dir: 'asc'});
    setPage(1);
  }

  const total = sorted.length;
  const pages = Math.max(1, Math.ceil(total / size));
  const current = Math.min(page, pages);
  const start = (current - 1) * size;
  const rows = sorted.slice(start, start + size);
  // 페이지 번호는 지금 페이지 앞뒤 2개까지만 보여 준다
  const numbers = Array.from({length: pages}, (_, i) => i + 1).filter(n => Math.abs(n - current) <= 2 || n === 1 || n === pages);

  return <section className="history-panel vessel-results" aria-label="입항 예정 선박">
    <div className="table-toolbar">
      <SectionTitle label={data.place ? `${data.place}에서 들른 배` : '부산 입항 예정 배'} kicker="ARRIVALS TO BUSAN" side={<span className="subtle-badge">{total}척 · {data.days ?? 7}일</span>}/>
      {data.ports.length > 0 && <div className="port-chips">{data.ports.map(p => <span key={p} className="role-chip"><Anchor size={11}/>{p}</span>)}</div>}
    </div>
    {total ? <>
      <div className="table-scroll" role="region" aria-label="입항 예정 선박 표" tabIndex={0}><table>
        <thead><tr>{COLUMNS.map(c => {
          const on = sort?.key === c.key;
          const Icon = on ? (sort!.dir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown;
          return <th key={c.key} aria-sort={on ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
            <button type="button" className={`sort-head ${on ? 'on' : ''}`} onClick={() => toggle(c.key)}>{c.label}<Icon size={12}/></button></th>;
        })}</tr></thead>
        <tbody>{rows.map((v, i) => <tr key={`${v.call_sign}-${start + i}`}>
          <td><strong>{v.ship_name}</strong></td><td className="mono">{shown(v.call_sign)}</td>
          <td>{shown(v.nationality)}</td><td>{shown(v.ship_kind)}</td>
          <td className="mono">{shown(v.previous_port)}</td>
          <td className="mono">{dateTime(v.expected_arrival)}</td><td className="mono">{dateTime(v.planned_departure)}</td>
          <td className="mono">{shown(v.next_port)}</td><td>{shown(v.facility)}</td><td>{shown(v.purpose)}</td>
        </tr>)}</tbody></table></div>
      <nav className="pager" aria-label="선박 표 페이지">
        <label className="pager-size">한 페이지
          <select value={size} onChange={e => { setSize(Number(e.target.value)); setPage(1); }} aria-label="한 페이지에 볼 선박 수">
            {PAGE_SIZES.map(n => <option key={n} value={n}>{n}개씩 보기</option>)}
          </select></label>
        <span className="pager-range mono">{start + 1}-{Math.min(start + size, total)} / {total}</span>
        <div className="pager-buttons">
          <button type="button" className="icon-button" onClick={() => setPage(current - 1)} disabled={current <= 1} aria-label="이전 페이지"><ChevronLeft size={15}/></button>
          {numbers.map((n, i) => <span key={n} className="pager-num-wrap">
            {i > 0 && n - numbers[i - 1] > 1 && <span className="pager-gap">…</span>}
            <button type="button" className={`pager-num ${n === current ? 'active' : ''}`} onClick={() => setPage(n)} aria-current={n === current ? 'page' : undefined}>{n}</button>
          </span>)}
          <button type="button" className="icon-button" onClick={() => setPage(current + 1)} disabled={current >= pages} aria-label="다음 페이지"><ChevronRight size={15}/></button>
        </div>
      </nav>
    </> : <div className="empty-state"><Ship/><h2>조건에 맞는 입항 예정 선박이 없습니다.</h2><p>{data.reply}</p></div>}
    <div className="table-bottom"><span>출처: 해양수산부 선박운항정보(입항 신고)</span><span>직전 기항지 기준이며 처음 출발한 항구·시각은 신고에 없습니다. 내 화물은 B/L 번호로 물어보세요.</span></div>
  </section>;
}
