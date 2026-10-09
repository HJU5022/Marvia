'use client';
/** 내 화물 현황 표. 수입자가 엑셀에 손으로 쓰던 "신용장 개설일 | 신용장 번호 | B/L 번호 | 출항 | 입항 | 입고" 표를 화면에 옮긴 것이다.
 *
 * 누가 채우나: 입항·입고·포워더·선사·컨테이너는 서버가 UNI-PASS에서 자동으로 채운다(읽기만).
 * 신용장 번호·개설일과 출항일은 사용자가 이 화면에서 직접 적는다(PUT /api/cargo/sheet/{cargo_key}/lc, /departed).
 * 신용장 하나에 B/L이 여러 개라서 신용장 칸은 묶음의 첫 줄에만 보이고 rowSpan으로 아래 줄까지 이어진다.
 *
 * 화면 모양: 제목 영역(영문 작은 글씨·큰 제목·한 줄 설명)과 엑셀 받기를 위에, 격자선이 있는 흰 카드 표를 아래에 둔다.
 * B/L 칸은 위에서부터 가린 B/L(mono) → 품명(가장 굵게) → 선명·국적 순이다. 시안은 품명이 작았지만 품명이 제일 눈에 띄어야 해서 굵기로 올렸다.
 * 선명·국적은 021 새 칸(vessel_name, vessel_flag)이 있는 줄에만 보인다. 없으면 만들어 쓰지 않고 대시로 자리만 둔다.
 * 좁은 화면(휴대폰)은 표 대신 줄마다 카드로 쌓는다(CSS만). 그래서 신용장 정보를 모든 줄 안에 작게 한 번 더 넣고, 넓은 화면에서는 CSS가 숨긴다.
 * 제목(h1)과 엑셀 받기 버튼은 같은 줄에 두려고 이 컴포넌트가 함께 그린다(상태가 여기 있어서).
 *
 * 수정 방식: 줄 끝의 "수정" 버튼이 그 줄 아래에 작은 편집 줄을 연다. 저장하면 서버가 돌려준 표 전체로 화면을 바꾼다.
 * 오류는 편집 줄 안에서 바로 보인다(role=alert). 닫으면 포커스를 "수정" 버튼으로 되돌린다.
 * 엑셀 받기는 출입증 헤더가 필요해서 링크가 아니라 blob으로 받아 내려 준다 (api.ts downloadCargoSheet).
 * 출처: 화물 현황 표 요청, 서버 계약은 lib/api.ts 상단 내 화물 현황 표 절. 시안: 마누스 3-1, 3-2 (S-xx).
 */
import {Fragment, useEffect, useRef, useState} from 'react';
import {Download, FileText, Info, LoaderCircle, Pencil, Table2} from 'lucide-react';
import {downloadCargoSheet, getCargoSheet, isLive, saveCargoDeparted, saveCargoLc} from '@/lib/api';
import type {CargoSheet as Sheet, CargoSheetRow} from '@/lib/types';

/** 표 칸 수(맨 끝 수정 버튼 칸 포함). 편집 줄이 신용장 두 칸(rowSpan으로 이어지는 칸)을 뺀 나머지를 가로로 채운다 */
const COLUMNS = 10;
const LC_COLUMNS = 2;

/** "2026-10-03" -> "10/3". 문자열로만 자른다(Date로 바꾸면 시간대 때문에 하루가 밀릴 수 있다) */
function md(value: string | null): string {
  const m = /^\d{4}-(\d{2})-(\d{2})/.exec(value ?? '');
  return m ? `${Number(m[1])}/${Number(m[2])}` : '';
}

/** 입항 칸: 실제 입항일이 있으면 그것, 없고 예정일이 있으면 "예정 M/D"를 흐리게. 둘 다 없으면 빈 칸 */
function ArrivedCell({row}: {row: CargoSheetRow}) {
  if (row.arrived_on) return <>{md(row.arrived_on)}</>;
  if (row.eta) return <span className="cargo-eta">예정 {md(row.eta)}</span>;
  return <Dash/>;
}

/** 값이 없는 칸의 자리 표시. 줄마다 칸이 비어 보이면 "빠졌나?" 싶어서 대시를 둔다 */
function Dash() { return <span className="cargo-empty" aria-label="없음">-</span>; }

/** 값이 있으면 글자, 없으면 대시 */
function Text({value}: {value: string | null}) { return value ? <>{value}</> : <Dash/>; }

export function CargoSheet() {
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [loadError, setLoadError] = useState('');
  const [editing, setEditing] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState('');
  // 편집을 닫은 뒤 포커스를 돌려줄 "수정" 버튼들
  const editButtons = useRef(new Map<string, HTMLButtonElement>());
  const returnFocusTo = useRef<string | null>(null);

  useEffect(() => {
    let alive = true;
    getCargoSheet()
      .then(s => { if (alive) setSheet(s); })
      .catch(e => { if (alive) setLoadError(e instanceof Error ? e.message : '화물 표를 불러오지 못했어요.'); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (editing === null && returnFocusTo.current) {
      editButtons.current.get(returnFocusTo.current)?.focus();
      returnFocusTo.current = null;
    }
  }, [editing]);

  function close(key: string) { returnFocusTo.current = key; setEditing(null); }

  async function exportXlsx() {
    setExporting(true); setExportError('');
    try {
      const {blob, filename} = await downloadCargoSheet();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (e) { setExportError(e instanceof Error ? e.message : '엑셀 파일을 받지 못했어요.'); }
    finally { setExporting(false); }
  }

  const empty = sheet !== null && sheet.groups.every(g => g.rows.length === 0);
  // 표 위 요약 줄: 서버가 준 칸만으로 센다. 끝난 화물은 완료, 입항일이 있으면 입항, 나머지는 운송 중
  const allRows = sheet ? sheet.groups.flatMap(g => g.rows) : [];
  const counts = {
    total: allRows.length,
    sailing: allRows.filter(r => r.status !== 'done' && !r.arrived_on).length,
    arrived: allRows.filter(r => r.status !== 'done' && r.arrived_on).length,
    done: allRows.filter(r => r.status === 'done').length,
  };

  return <div className="cargo-sheet">
    <header className="cs-head">
      <div className="cs-title">
        <h1>내 화물 현황</h1>
        <p>신용장별 출항·입항·입고를 한눈에 확인해 보세요.</p>
      </div>
      <div className="cs-actions">
        <button type="button" className="cs-btn cs-btn-outline cs-export" onClick={() => void exportXlsx()} disabled={exporting || !sheet || empty}>
          {exporting ? <LoaderCircle size={20} className="spin"/> : <Download size={20}/>}엑셀 받기</button>
      </div>
    </header>
    {sheet && !empty && <dl className="cs-summary" aria-label="화물 현황 요약">
      <div><dt>전체</dt><dd>{counts.total}</dd></div>
      <div><dt>운송 중</dt><dd>{counts.sailing}</dd></div>
      <div><dt>입항</dt><dd>{counts.arrived}</dd></div>
      <div><dt>완료</dt><dd>{counts.done}</dd></div>
    </dl>}
    {exportError && <p role="alert" className="request-error">{exportError}</p>}
    {loadError ? <p role="alert" className="request-error">{loadError}</p>
    : !sheet ? <div className="empty-state" role="status"><Table2/><h2>화물 표를 불러오고 있어요.</h2></div>
    : empty ? <div className="empty-state"><Table2/><h2>아직 표에 올라온 화물이 없어요.</h2><p>홈에서 B/L 번호를 조회하면 이 표에 화물이 추가돼요.</p></div>
    : <div className="cs-card table-scroll" role="region" aria-label="내 화물 현황 표" tabIndex={0}>
      <table>
        <caption className="sr-only">신용장별 화물 현황</caption>
        <thead><tr>
          <th className="cs-th-lc">신용장<br/>개설일</th><th className="cs-th-lc">신용장<br/>번호</th><th className="cs-th-item">B/L 번호</th><th>출항</th><th>입항</th><th>입고</th><th>포워더</th><th>선사</th><th>컨테이너</th><th className="cs-th-edit"><span className="sr-only">수정</span></th>
        </tr></thead>
        <tbody>
          {sheet.groups.map(g => {
            const rows = g.rows;
            // 편집 줄이 이 묶음 안에 끼면 rowSpan이 그만큼 늘어야 신용장 칸이 끊기지 않는다
            const span = rows.length + (rows.some(r => r.cargo_key === editing) ? 1 : 0);
            return rows.map((r, ri) => <Fragment key={r.cargo_key}>
              <tr className={['cargo-row', r.status === 'done' ? 'cargo-done' : '', ri === 0 ? 'cargo-group-start' : '', editing === r.cargo_key ? 'cargo-editing' : ''].filter(Boolean).join(' ')}>
                {ri === 0 && <>
                  <td rowSpan={span} className="cargo-lc cargo-lc-date">{g.lc ? (md(g.lc.opened_on) || <Dash/>) : ''}</td>
                  <td rowSpan={span} className="cargo-lc cargo-lc-no">{g.lc ? g.lc.lc_no : <span className="cargo-unlinked">신용장 미연결</span>}</td>
                </>}
                <td className="cargo-item">
                  {/* 휴대폰 카드에서만 보이는 신용장 줄. 넓은 화면은 rowSpan 두 칸이 이 일을 한다 */}
                  <div className="cargo-lc-inline">{g.lc ? <>{g.lc.lc_no}{md(g.lc.opened_on) && <> · 개설 {md(g.lc.opened_on)}</>}</> : '신용장 미연결'}</div>
                  <div className="cargo-bl-row">
                    <span className="cargo-bl mono">{r.bl_masked}</span>
                    {r.status === 'done' && <span className="cargo-badge">완료</span>}
                  </div>
                  {/* 품명(goods_name)이 첫째, 없으면 사용자가 붙인 이름(label), 둘 다 없으면 대시 */}
                  <div className="cargo-label-row">{r.goods_name || r.label ? <strong className="cargo-label">{r.goods_name || r.label}</strong> : <span className="cargo-label cargo-label-none"><Dash/></span>}</div>
                  <div className="cargo-vessel">{r.vessel_name ? <>{r.vessel_name}{r.vessel_flag && <> · {r.vessel_flag}</>}</> : <Dash/>}</div>
                </td>
                <td data-label="출항" className="cargo-date">{md(r.departed_on) || <Dash/>}{r.departed_source === 'document' && md(r.departed_on) && <span className="cargo-doc" title="도착 통지서에서 읽음" aria-label="도착 통지서에서 읽음"><FileText size={15}/></span>}</td>
                <td data-label="입항" className="cargo-date"><ArrivedCell row={r}/></td>
                <td data-label="입고" className="cargo-date">{md(r.warehoused_on) || <Dash/>}</td>
                <td data-label="포워더"><Text value={r.forwarder_name}/></td>
                <td data-label="선사"><Text value={r.carrier_name}/></td>
                <td data-label="컨테이너" className={r.container_no ? 'mono' : undefined}><Text value={r.container_no}/></td>
                <td className="cargo-edit-cell"><button type="button" className="cargo-edit"
                  ref={el => { if (el) editButtons.current.set(r.cargo_key, el); else editButtons.current.delete(r.cargo_key); }}
                  aria-expanded={editing === r.cargo_key} aria-label={`${r.bl_masked} 신용장·출항 수정`} title="수정"
                  onClick={() => setEditing(editing === r.cargo_key ? null : r.cargo_key)}><Pencil size={16} strokeWidth={1.9} aria-hidden="true"/></button></td>
              </tr>
              {editing === r.cargo_key && <tr className="cargo-editor-row"><td colSpan={COLUMNS - LC_COLUMNS}><div className="cargo-editor-slide">
                <RowEditor row={r} lcNo={g.lc?.lc_no ?? ''} openedOn={g.lc?.opened_on ?? ''} onSaved={s => { setSheet(s); close(r.cargo_key); }} onCancel={() => close(r.cargo_key)}/>
              </div></td></tr>}
            </Fragment>);
          })}
        </tbody>
      </table>
    </div>}
    {sheet?.truncated && <p className="cs-truncated" role="status">화물이 많아 앞쪽 500건만 보여 드려요.</p>}
    {!isLive && sheet && <p className="cs-demo-note"><Info size={16} aria-hidden="true"/>체험 모드에서는 고친 내용이 새로고침하면 처음으로 돌아가요.</p>}
  </div>;
}

/** 한 줄의 신용장(번호·개설일)과 출항일을 고치는 편집 칸. 두 저장 버튼은 따로 서버를 부른다.
 *  버튼 위계(시안 3-2): 저장 둘은 파랑 채움, 풀기·닫기는 테두리 버튼. 두 채움 버튼이 한 줄에 있어도 가운데 세로선으로
 *  "신용장 묶음"과 "출항일" 두 일을 갈라서 어느 저장이 무엇을 저장하는지 헷갈리지 않게 한다. */
function RowEditor({row, lcNo, openedOn, onSaved, onCancel}: {
  row: CargoSheetRow; lcNo: string; openedOn: string;
  onSaved: (s: Sheet) => void; onCancel: () => void;
}) {
  const id = row.cargo_key;
  const [lc, setLc] = useState(lcNo);
  const [opened, setOpened] = useState(openedOn);
  const [departed, setDeparted] = useState(row.departed_on ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => { first.current?.focus(); }, []);

  // 저장 두 개와 풀기가 같은 흐름이라 하나로 묶었다: 부르고, 성공하면 표를 바꾸고, 실패하면 이 칸에 오류를 보인다
  async function run(call: () => Promise<Sheet>) {
    setBusy(true); setError('');
    try { onSaved(await call()); }
    catch (e) { setError(e instanceof Error ? e.message : '저장하지 못했어요.'); setBusy(false); }
  }

  function saveLc() {
    const no = lc.trim();
    if (!no) { setError('신용장 번호를 입력해 주세요. 신용장 연결을 끊으려면 "신용장 연결 해제"를 눌러 주세요.'); return; }
    void run(() => saveCargoLc(row.cargo_key, no, opened || null));
  }

  return <form className="cargo-editor" aria-label={`${row.bl_masked} 수정`}
    onSubmit={e => e.preventDefault()} onKeyDown={e => { if (e.key === 'Escape') onCancel(); }}>
    <div className="cargo-editor-group cargo-editor-lc">
      <div className="cs-field cs-field-lc"><label htmlFor={`lc-${id}`}>신용장 번호</label>
        <input id={`lc-${id}`} ref={first} value={lc} onChange={e => setLc(e.target.value)} maxLength={40} disabled={busy}/></div>
      <div className="cs-field cs-field-date"><label htmlFor={`op-${id}`}>개설일</label>
        <input id={`op-${id}`} type="date" value={opened} onChange={e => setOpened(e.target.value)} disabled={busy}/></div>
      <div className="cargo-editor-buttons">
        <button type="button" className="cs-btn cs-btn-fill" onClick={saveLc} disabled={busy}>신용장 저장</button>
        {lcNo && <button type="button" className="cs-btn cs-btn-outline" onClick={() => void run(() => saveCargoLc(row.cargo_key, null, null))} disabled={busy}>신용장 연결 해제</button>}
      </div>
    </div>
    <div className="cargo-editor-group cargo-editor-departed">
      <div className="cs-field cs-field-date"><label htmlFor={`dp-${id}`}>출항일</label>
        <input id={`dp-${id}`} type="date" value={departed} onChange={e => setDeparted(e.target.value)} disabled={busy}/></div>
      <div className="cargo-editor-buttons">
        <button type="button" className="cs-btn cs-btn-fill" onClick={() => void run(() => saveCargoDeparted(row.cargo_key, departed || null))} disabled={busy}>출항일 저장</button>
        <button type="button" className="cs-btn cs-btn-outline" onClick={onCancel} disabled={busy}>닫기</button>
      </div>
    </div>
    {/* 오류 칸은 늘 있고 글만 바뀐다(WatchToggle과 같은 방식). 비면 CSS가 안 보이게 한다 */}
    <p role="alert" className="request-error">{error}</p>
  </form>;
}
