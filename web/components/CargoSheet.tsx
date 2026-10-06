'use client';
/** 내 화물 현황 표. 수입자가 엑셀에 손으로 쓰던 "신용장 개설일 | 신용장 번호 | B/L 번호 | 출항 | 입항 | 입고" 표를 화면에 옮긴 것이다.
 *
 * 누가 채우나: 입항·입고·포워더·선사·컨테이너는 서버가 UNI-PASS에서 자동으로 채운다(읽기만).
 * 신용장 번호·개설일과 출항일은 사용자가 이 화면에서 직접 적는다(PUT /api/cargo/sheet/{cargo_key}/lc, /departed).
 * 신용장 하나에 B/L이 여러 개라서 신용장 칸은 묶음의 첫 줄에만 보이고 rowSpan으로 아래 줄까지 이어진다.
 *
 * 수정 방식: 줄 끝의 "수정" 버튼이 그 줄 아래에 작은 편집 줄을 연다. 저장하면 서버가 돌려준 표 전체로 화면을 바꾼다.
 * 오류는 편집 줄 안에서 바로 보인다(role=alert). 닫으면 포커스를 "수정" 버튼으로 되돌린다.
 * 엑셀 받기는 출입증 헤더가 필요해서 링크가 아니라 blob으로 받아 내려 준다 (api.ts downloadCargoSheet).
 * 출처: 10-06 화물 현황 표 요청, 서버 계약은 lib/api.ts 상단 내 화물 현황 표 절. 화면은 나중에 전체 개편 예정이라 최소로 둔다.
 */
import {Fragment, useEffect, useRef, useState} from 'react';
import {Download, FileText, LoaderCircle, Pencil, Table2} from 'lucide-react';
import {downloadCargoSheet, getCargoSheet, saveCargoDeparted, saveCargoLc} from '@/lib/api';
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
  return null;
}

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
      .catch(e => { if (alive) setLoadError(e instanceof Error ? e.message : '화물 표를 불러오지 못했습니다.'); });
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
    } catch (e) { setExportError(e instanceof Error ? e.message : '엑셀을 받지 못했습니다.'); }
    finally { setExporting(false); }
  }

  const empty = sheet !== null && sheet.groups.every(g => g.rows.length === 0);

  return <div className="cargo-sheet">
    <div className="cargo-sheet-bar">
      <p className="muted">입항·입고와 포워더·선사·컨테이너는 관세청 조회 결과로 자동으로 채워집니다. 신용장과 출항일은 직접 적어 주세요.</p>
      <button type="button" className="button secondary" onClick={() => void exportXlsx()} disabled={exporting || !sheet || empty}>
        {exporting ? <LoaderCircle size={15} className="spin"/> : <Download size={15}/>}엑셀 받기</button>
    </div>
    {exportError && <p role="alert" className="request-error">{exportError}</p>}
    {loadError ? <p role="alert" className="request-error">{loadError}</p>
    : !sheet ? <div className="empty-state" role="status"><Table2/><h2>화물 표를 불러오는 중입니다.</h2></div>
    : empty ? <div className="empty-state"><Table2/><h2>아직 표에 올라온 화물이 없습니다.</h2><p>홈에서 B/L 번호를 한 번 조회하면 이 표에 줄이 생깁니다.</p></div>
    : <div className="table-scroll" role="region" aria-label="내 화물 현황 표" tabIndex={0}>
      <table>
        <caption className="sr-only">신용장별 화물 현황</caption>
        <thead><tr>
          <th>신용장 개설일</th><th>신용장 번호</th><th>B/L 번호</th><th>출항</th><th>입항</th><th>입고</th><th>포워더</th><th>선사</th><th>컨테이너</th><th><span className="sr-only">수정</span></th>
        </tr></thead>
        <tbody>
          {sheet.groups.map((g, gi) => {
            const rows = g.rows;
            // 편집 줄이 이 묶음 안에 끼면 rowSpan이 그만큼 늘어야 신용장 칸이 끊기지 않는다
            const span = rows.length + (rows.some(r => r.cargo_key === editing) ? 1 : 0);
            return rows.map((r, ri) => <Fragment key={r.cargo_key}>
              <tr className={r.status === 'done' ? 'cargo-done' : undefined}>
                {ri === 0 && <>
                  <td rowSpan={span} className="cargo-lc">{g.lc ? md(g.lc.opened_on) : ''}</td>
                  <td rowSpan={span} className="cargo-lc">{g.lc ? g.lc.lc_no : <span className="muted">신용장 미연결</span>}</td>
                </>}
                <td className="mono">{r.bl_masked}{r.label && <small className="cargo-label">{r.label}</small>}{r.status === 'done' && <span className="subtle-badge cargo-badge">완료</span>}</td>
                <td>{md(r.departed_on)}{r.departed_source === 'document' && md(r.departed_on) && <span className="cargo-doc" title="도착 통지서에서 읽음" aria-label="도착 통지서에서 읽음"><FileText size={12}/></span>}</td>
                <td><ArrivedCell row={r}/></td>
                <td>{md(r.warehoused_on)}</td>
                <td>{r.forwarder_name}</td>
                <td>{r.carrier_name}</td>
                <td className="mono">{r.container_no}</td>
                <td className="cargo-edit-cell"><button type="button" className="cargo-edit"
                  ref={el => { if (el) editButtons.current.set(r.cargo_key, el); else editButtons.current.delete(r.cargo_key); }}
                  aria-expanded={editing === r.cargo_key} aria-label={`${r.bl_masked} 신용장·출항 수정`}
                  onClick={() => setEditing(editing === r.cargo_key ? null : r.cargo_key)}><Pencil size={13}/>수정</button></td>
              </tr>
              {editing === r.cargo_key && <tr className="cargo-editor-row"><td colSpan={COLUMNS - LC_COLUMNS}>
                <RowEditor row={r} lcNo={g.lc?.lc_no ?? ''} openedOn={g.lc?.opened_on ?? ''} onSaved={s => { setSheet(s); close(r.cargo_key); }} onCancel={() => close(r.cargo_key)}/>
              </td></tr>}
            </Fragment>);
          })}
        </tbody>
      </table>
    </div>}
  </div>;
}

/** 한 줄의 신용장(번호·개설일)과 출항일을 고치는 작은 편집 칸. 두 저장 버튼은 따로 서버를 부른다 */
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
    catch (e) { setError(e instanceof Error ? e.message : '저장하지 못했습니다.'); setBusy(false); }
  }

  function saveLc() {
    const no = lc.trim();
    if (!no) { setError('신용장 번호를 적어 주세요. 묶음을 풀려면 "신용장 풀기"를 누르세요.'); return; }
    void run(() => saveCargoLc(row.cargo_key, no, opened || null));
  }

  return <form className="cargo-editor" aria-label={`${row.bl_masked} 수정`}
    onSubmit={e => e.preventDefault()} onKeyDown={e => { if (e.key === 'Escape') onCancel(); }}>
    <div className="cargo-editor-group">
      <div className="form-field"><label htmlFor={`lc-${id}`}>신용장 번호</label>
        <input id={`lc-${id}`} ref={first} value={lc} onChange={e => setLc(e.target.value)} maxLength={40} disabled={busy}/></div>
      <div className="form-field"><label htmlFor={`op-${id}`}>개설일</label>
        <input id={`op-${id}`} type="date" value={opened} onChange={e => setOpened(e.target.value)} disabled={busy}/></div>
      <button type="button" className="button primary" onClick={saveLc} disabled={busy}>신용장 저장</button>
      {lcNo && <button type="button" className="button secondary" onClick={() => void run(() => saveCargoLc(row.cargo_key, null, null))} disabled={busy}>신용장 풀기</button>}
    </div>
    <div className="cargo-editor-group">
      <div className="form-field"><label htmlFor={`dp-${id}`}>출항일</label>
        <input id={`dp-${id}`} type="date" value={departed} onChange={e => setDeparted(e.target.value)} disabled={busy}/></div>
      <button type="button" className="button primary" onClick={() => void run(() => saveCargoDeparted(row.cargo_key, departed || null))} disabled={busy}>출항일 저장</button>
    </div>
    <button type="button" className="button secondary" onClick={onCancel} disabled={busy}>닫기</button>
    {/* 오류 칸은 늘 있고 글만 바뀐다(WatchToggle과 같은 방식). 비면 CSS가 안 보이게 한다 */}
    <p role="alert" className="request-error">{error}</p>
  </form>;
}
