'use client';
/** 입항 예정 선박 검색 결과 (docs/specs/chat-search.md vessel_search). 오른쪽 칸 구성:
 * 맨 위에 큰 지도(VesselMap, 화물 상세 지도와 같은 모양과 지도 펼치기), 그 아래에 5칸짜리 가벼운 목록.
 * 줄을 누르면 지도가 그 배로 날아가고, 줄이 그 자리에서 펼쳐져 자세히(VesselDetail)가 나온다. 줄과 점은 서로 강조한다.
 * 위치는 배마다 ShipFinder를 한 번씩 불러야 알 수 있고 하루 50건 한도가 있다. 그래서 자동으로 받지 않고 선명을 누를 때만 받는다.
 * 받은 결과는 서버가 10분 캐시하므로 여기서도 같은 시간 동안 들고 있다(cache, 모듈 변수). 지도에는 지금 고른 배 하나만 찍는다.
 * 다른 배를 고르면 앞 배는 캐시에만 남고(점은 지운다), 10분이 지나면 캐시에서도 지운다. 그 뒤 다시 누르면 API를 부른다.
 * 해수부 입항 신고 기준이라 "직전 기항지"를 그대로 보여 준다. 출발지가 아니라는 점은 줄 펼침의 출처 안내에 있다 (EC-04). 판정은 하지 않는다.
 * 수십 척이 나올 수 있어 화면에서 페이지로 나눈다. 한 페이지 10·30·50척 중 고른다(기본 10).
 * 표에 두지 못한 값(호출부호, 선박 종류, 다음에 들를 항구, 목적)은 펼친 줄 안으로 옮겼다. 가로로 밀리는 표가 되지 않게 5칸만 둔다.
 */
import {Fragment, useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Ship, SlidersHorizontal} from 'lucide-react';
import {VesselDetail, type DetailEntry} from './VesselDetail';
import {VesselMap, type MapShip} from './VesselMap';
import {WatchVesselButton} from './WatchVesselButton';
import {useApp} from './AppProvider';
import {getVesselDetail} from '@/lib/api';
import {dateTime, placeLabel} from '@/lib/format';
import type {ChatResponse, VesselItem} from '@/lib/types';

const PAGE_SIZES = [10, 30, 50] as const;
/** 서버가 자세히 결과를 캐시하는 시간(10분)과 같다. 이보다 오래된 결과는 줄을 다시 누를 때 새로 받는다 */
const FRESH_MS = 10 * 60 * 1000;

/** 정렬할 수 있는 5칸. 시각 칸은 ISO 문자열이라 글자 순서가 곧 시간 순서다 */
/** 직전 기항지가 이 곳 수 이하면 접지 않고 바로 보인다 */
const PORTS_INLINE_MAX = 5;
const COLUMNS: {key: keyof VesselItem; label: string; cls: string}[] = [
  {key: 'ship_name', label: '선박 이름', cls: 'c-name'}, {key: 'nationality', label: '국적', cls: 'c-flag'},
  {key: 'previous_port', label: '직전에 들른 항구', cls: 'c-prev'}, {key: 'expected_arrival', label: '부산 입항 예정', cls: 'c-eta'},
  {key: 'planned_departure', label: '부산 출항 예정', cls: 'c-etd'},
];

/** 표 칸의 빈 값은 "확인되지 않음" 대신 줄표로 (좁은 칸, 시안) */
const cell = (x: string | null | undefined) => x ? x : '-';
const when = (x: string | null | undefined) => x ? dateTime(x, true) : '-';
/** 줄과 지도 점을 잇는 이름 */
const keyOf = (v: {call_sign: string | null; ship_name: string}) => `${v.call_sign ?? ''}|${v.ship_name}`;

/** 이 세션에서 받은 자세히 결과. 새 검색을 해도 남아서 지도에 계속 찍힌다 */
const cache = new Map<string, DetailEntry>();

export function VesselList({data}: {data: ChatResponse}) {
  const [size, setSize] = useState<number>(PAGE_SIZES[0]);
  const [page, setPage] = useState(1);
  // 지도가 보여 주는 배(sel)와 그 줄이 펼쳐졌는지(expanded). 고르지 않았으면 표의 첫 줄 배가 지도에 나온다
  const [sel, setSel] = useState<VesselItem | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const [entries, setEntries] = useState<Record<string, DetailEntry>>(() => Object.fromEntries(cache));
  const inflight = useRef(new Set<string>());
  const listRef = useRef<HTMLDivElement>(null);
  // 기본은 수입 화물선만. 서버가 배마다 is_cargo를 붙여 보낸다(기준 목록은 skills/port-busan/cargo-vessels.md)
  const [allKinds, setAllKinds] = useState(false);
  // 기본은 서버가 준 순서(부산 입항 예정 빠른 순)
  const [sort, setSort] = useState<{key: keyof VesselItem; dir: 'asc' | 'desc'} | null>(null);
  // 새 검색 결과가 오면 첫 페이지, 정렬 처음으로
  useEffect(() => { setPage(1); setSort(null); setSel(null); setExpanded(false); setAllKinds(false); }, [data]);

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

  /** 한 배의 자세히를 받는다. 이미 받았거나(10분 안) 받는 중이면 다시 부르지 않는다. 받는 중에 오래된 결과가 있으면 그대로 두고 교체만 한다 */
  const load = useCallback((v: VesselItem) => {
    const k = keyOf(v), e = cache.get(k);
    if (inflight.current.has(k) || (e?.status === 'done' && Date.now() - e.at < FRESH_MS)) return;
    inflight.current.add(k);
    const put = (n: DetailEntry) => { cache.set(k, n); setEntries(s => ({...s, [k]: n})); };
    if (e?.status !== 'done') put({status: 'loading'});
    getVesselDetail(v.call_sign, v.ship_name)
      .then(d => put({status: 'done', data: d, at: Date.now()}))
      .catch(err => { if (e?.status !== 'done') put({status: 'error', message: err instanceof Error ? err.message : '자세한 정보를 불러오지 못했어요.'}); })
      .finally(() => inflight.current.delete(k));
  }, []);

  // 처음에는 아무 배도 고르지 않는다. 선명을 눌렀을 때만 위치를 받는다 (전에는 첫 줄을 자동으로 골라
  // 묻지도 않은 배의 상세가 열리고 ShipFinder 하루 한도를 썼다)
  const selected = sel && sorted.includes(sel) ? sel : null;
  const selKey = selected ? keyOf(selected) : null;
  // 고른 배를 앱에 알린다. 채팅이 "이 배 지켜봐 줘"의 그 배를 on_screen의 selected로 받는다. 해제·목록이 사라질 때는 null
  const {setSelectedArrival} = useApp();
  useEffect(() => { setSelectedArrival(selected ? {name: selected.ship_name, call_sign: selected.call_sign ?? null} : null); }, [selKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => setSelectedArrival(null), [setSelectedArrival]);

  function pick(v: VesselItem) {
    if (selected === v && expanded) { setExpanded(false); return; }
    setSel(v); setExpanded(true); load(v);
  }
  // 지도의 점을 눌렀을 때: 그 배가 이 목록에 있으면 고른 것으로 친다. 다른 쪽 페이지에 있으면 그 페이지로 넘긴다
  const onMarker = useCallback((k: string) => {
    const i = sorted.findIndex(v => keyOf(v) === k); if (i < 0) return;
    setPage(Math.floor(i / size) + 1); setSel(sorted[i]); setExpanded(true); load(sorted[i]);
  }, [sorted, size, load]);
  // 펼친 줄이 화면 밖일 수 있어, 고르거나 펼친 뒤에는 그 줄이 목록 맨 위에 오게 목록만 스크롤한다.
  // scrollIntoView는 위쪽 칸(지도가 있는 칸)까지 밀 수 있어서 목록 칸만 직접 움직인다
  useEffect(() => {
    if (!selKey || !expanded) return;
    const id = requestAnimationFrame(() => {
      const box = listRef.current, row = box?.querySelector(`[data-vkey="${CSS.escape(selKey)}"]`);
      if (!box || !row) return;
      const top = row.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop - 12;
      box.scrollTo({top: Math.max(0, top), behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
    });
    return () => cancelAnimationFrame(id);
  }, [selKey, expanded, page]);

  // 10분이 지난 배는 캐시와 화면 상태에서 지운다. 1분마다 본다 (서버 vessel_detail.CACHE_SEC와 같은 10분).
  // 지금 고른 배는 지우지 않는다: 지우면 펼친 칸이 "불러오는 중"으로 멈춘다. 그 배는 다시 고를 때 10분이 지났으면 새로 받는다
  const selRef = useRef<string | null>(null);
  selRef.current = selKey;
  useEffect(() => {
    const id = window.setInterval(() => {
      const now = Date.now();
      const old = [...cache.entries()].filter(([k, e]) => k !== selRef.current && e.status === 'done' && now - e.at >= FRESH_MS).map(([k]) => k);
      if (!old.length) return;
      old.forEach(k => cache.delete(k));
      setEntries(s => { const n = {...s}; old.forEach(k => { delete n[k]; }); return n; });
    }, 60 * 1000);
    return () => window.clearInterval(id);
  }, []);

  // 지도에 찍을 배: 지금 고른 배 하나 (전에는 이 세션에서 받은 배가 모두 점으로 남았다)
  const ships = useMemo<MapShip[]>(() => {
    const e = selKey ? entries[selKey] : undefined;
    const pos = e?.status === 'done' ? e.data.position : null;
    return pos && selKey ? [{key: selKey, name: e?.status === 'done' && e.data.vessel?.name || selKey.split('|')[1], lat: pos.lat, lng: pos.lng, sog: pos.sog, cog: pos.cog, freshness: pos.freshness}] : [];
  }, [entries, selKey]);
  const selEntry = selKey ? entries[selKey] : undefined;
  const selData = selEntry?.status === 'done' ? selEntry.data : null;
  const route = useMemo(() => selData?.position?.route ?? [], [selData]);
  const selectedMissing = !!selEntry && (selEntry.status === 'error' || (selEntry.status === 'done' && !selEntry.data.position));

  const total = sorted.length;
  const pages = Math.max(1, Math.ceil(total / size));
  const current = Math.min(page, pages);
  const start = (current - 1) * size;
  const rows = sorted.slice(start, start + size);
  // 페이지 번호는 지금 페이지 앞뒤 2개까지만 보여 준다
  const numbers = Array.from({length: pages}, (_, i) => i + 1).filter(n => Math.abs(n - current) <= 2 || n === 1 || n === pages);

  return <section className="history-panel vessel-results vl" aria-label="입항 예정 선박">
    <VesselMap ships={ships} selectedKey={selected ? selKey : null} hoverKey={hover} route={route} distanceNm={selData?.distance?.distance_nm ?? null}
      selectedMissing={selectedMissing} onSelect={onMarker} onHover={setHover}/>
    <div className="vl-body" ref={listRef}>
    <header className="vl-head">
      <div>
        <h2>{data.place ? `${placeLabel(data.place)}에서 들른 배` : '부산 입항 예정 배'}</h2>
        <p className="vl-meta">{total}척 · {data.days ?? 7}일 · 모든 시각 한국 시간</p>
        {/* 항구 이름이 많으면(40곳) 한 줄로 이어 붙이지 않고 접어 둔다. 5곳 이하는 바로 보인다 */}
        {data.ports.length > 0 && (data.ports.length <= PORTS_INLINE_MAX
          ? <div className="vl-ports vl-ports-line"><b>직전 기항지 {data.ports.length}곳</b><ul className="vl-chips">{data.ports.map(p => <li key={p}>{p}</li>)}</ul></div>
          : <details className="vl-ports"><summary><b>직전 기항지 {data.ports.length}곳</b><span className="vl-ports-btn">항구 보기</span></summary>
              <ul className="vl-chips">{data.ports.map(p => <li key={p}>{p}</li>)}</ul></details>)}
      </div>
      <button type="button" className="vl-kinds-toggle" aria-pressed={allKinds}
        onClick={() => { setAllKinds(v => !v); setPage(1); setSel(null); setExpanded(false); }}><SlidersHorizontal size={16} strokeWidth={1.75}/>{allKinds ? '수입 화물선만 보기' : '모든 선박 종류 보기'}</button>
    </header>
    {total ? <>
      <div className="vl-table" role="region" aria-label="입항 예정 선박 표"><table>
        <thead><tr>{COLUMNS.map(c => {
          const on = sort?.key === c.key;
          const Icon = on ? (sort!.dir === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown;
          return <th key={c.key} className={c.cls} aria-sort={on ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
            <button type="button" className={`sort-head ${on ? 'on' : ''}`} onClick={() => toggle(c.key)}>{c.label}<Icon size={14}/></button></th>;
        })}</tr></thead>
        <tbody>{rows.map((v, i) => {
          const k = keyOf(v), isSel = selected === v, open = isSel && expanded;
          return <Fragment key={`${k}-${start + i}`}>
            <tr data-vkey={k} className={`${open ? 'row-open' : ''}${isSel ? ' row-sel' : ''}${hover === k ? ' row-hl' : ''}`}
              onClick={() => pick(v)} onMouseEnter={() => setHover(k)} onMouseLeave={() => setHover(null)}>
              <td className="c-name"><div className="vl-name">
                <button type="button" className="ship-link" onClick={e => { e.stopPropagation(); pick(v); }} aria-pressed={open} aria-expanded={open}>{v.ship_name}</button>
                {/* 자세히를 이미 받은 줄은 그 결과의 MMSI로 올려 서버가 다시 찾지 않게 한다. 못 받은 줄은 호출부호+이름을 보내고 서버가 이름으로 가린다 */}
                {/* 해수부 신고에는 MMSI가 없어 호출부호로 올린다(서버가 찾는다). 호출부호가 없는 배는 지켜볼 수 없어 버튼을 그리지 않는다 */}
                {v.call_sign ? <span className="vl-watch" onClick={e => e.stopPropagation()}><WatchVesselButton mmsi={(entries[k]?.status === 'done' ? entries[k].data.vessel?.mmsi : null) ?? null} callSign={v.call_sign} name={v.ship_name} flag={v.nationality} eta={v.expected_arrival}/></span> : null}
              </div></td>
              <td className="c-flag">{cell(v.nationality)}</td>
              <td className="c-prev">{cell(v.previous_port)}</td>
              <td className="c-eta">{when(v.expected_arrival)}</td>
              <td className="c-etd">{when(v.planned_departure)}</td>
            </tr>
            {open && <tr className="vl-exp"><td colSpan={COLUMNS.length}><VesselDetail vessel={v} entry={entries[k]}/></td></tr>}
          </Fragment>;
        })}</tbody></table></div>
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
    </div>
  </section>;
}
