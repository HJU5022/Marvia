'use client';
/** 설정 화면의 "내 기억" 구역 (docs/specs/memory.md "사용자는 메모장을 보고, 줄 하나 또는 전부 지울 수 있다").
 *
 * GET /api/memory로 Marvia가 기억한 화물과 메모를 보여 주고, 메모 한 줄(DELETE /api/memory/items/{id})이나
 * 전부(DELETE /api/memory)를 지운다. 지우기는 되돌릴 수 없어서 화면 안에서 한 번 더 확인한다 (AccountPanel과 같은 방식).
 * 원본 B/L은 서버가 보내지 않는다. 가린 번호와 이름표만 보인다.
 * 데모 모드는 가공 예시를 보여 주고 지우기는 막는다. 로그인이 꺼진 서버는 기억을 만들지 않는다 (EC-08).
 */
import {useCallback, useEffect, useState} from 'react';
import {Brain, LoaderCircle, Trash2} from 'lucide-react';
import {useApp} from './AppProvider';
import {SectionTitle} from './Shared';
import {deleteAllMemory, deleteMemoryItem, getMemory, isLive} from '@/lib/api';
import {day, verdictLabels} from '@/lib/format';
import type {CargoSummary, MemoryItem, MemoryResponse} from '@/lib/types';

const KIND_LABELS: Record<MemoryItem['kind'], string> = {
  preference: '선호', schedule: '반복 일정', contact: '거래처', worry: '걱정', todo: '할 일',
};
const PENDING_LABELS: Record<string, string> = {sale_due_date: '받아야 하는 날', forwarder_eta: '포워더가 알려 준 입항일', label: '화물 이름'};

/** 메모 한 줄을 사람이 읽는 글로. 칸 이름은 services/memory.py TEXT_LIMITS와 같다 */
function itemText(item: MemoryItem): string {
  const f = item.fields;
  if (item.kind === 'schedule') return `${f.cycle ?? ''} · ${f.task ?? ''}`;
  if (item.kind === 'contact') {
    const from = f.source === '사용자' ? '직접 알려 줌' : `${f.source}에서`;
    return `${[f.company, f.role, f.duty, f.phone].filter(Boolean).join(' · ')} (${from})`;
  }
  if (item.kind === 'todo') return `${f.text ?? ''}${f.done ? ' (끝남)' : ''}`;
  return String(f.text ?? '');
}

/** 시각을 한국 날짜 "10.01"로 (lib/format.ts와 같이 Asia/Seoul 기준). 읽을 수 없으면 빈 글자 */
function kstMonthDay(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.valueOf())) return '';
  return new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit'}).format(d).replace('-', '.');
}

/** 여유 일수를 사람 말로. 음수는 판매 예정일보다 늦게 도착한다는 뜻 (서버 cargo.margin_text와 같다) */
function margin(value: number | null): string | null {
  if (value === null) return null;
  return value >= 0 ? `여유 ${value}일` : `판매 예정일보다 ${Math.abs(value)}일 늦음`;
}

/** B/L 조건을 사람 말로. 모르는 칸은 말하지 않는다 */
function conditions(c: CargoSummary): string[] {
  const out: string[] = [];
  if (c.original_bl) out.push(c.original_bl === 'required' ? '원본 B/L 필요' : '서렌더(원본 B/L 불필요)');
  if (c.to_order_bank !== null) out.push(c.to_order_bank ? '은행 지시식' : '은행 지시식 아님');
  if (c.freight_term) out.push(`${c.freight_term === 'collect' ? '운임 착불' : '운임 선불'}${c.incoterm ? ` (${c.incoterm})` : ''}`);
  else if (c.incoterm) out.push(c.incoterm);
  return out;
}

function CargoRow({c}: {c: CargoSummary}) {
  const name = c.label ? `${c.label} (${c.bl_masked})` : c.bl_masked;
  if (c.status === 'done') return <li className="memory-cargo done"><strong>{c.summary ?? name}</strong><span className="subtle-badge">끝난 화물</span></li>;
  const last = c.last_checked_at && c.last_verdict
    ? `지난 조회 ${kstMonthDay(c.last_checked_at)}: ${[verdictLabels[c.last_verdict], margin(c.last_days_margin)].filter(Boolean).join(', ')}`
    : '아직 판정 기록이 없습니다';
  return <li className="memory-cargo">
    <strong>{name}</strong>
    <span>{last}</span>
    {c.sale_due_date && <span>받아야 하는 날 {day(c.sale_due_date)}</span>}
    {c.forwarder_eta && <span>포워더가 알려 준 입항일 {day(c.forwarder_eta)}</span>}
    {conditions(c).length > 0 && <span>{conditions(c).join(' · ')}</span>}
    {c.pending.map(p => <span key={p.field} className="memory-pending">
      대화에서 {PENDING_LABELS[p.field] ?? '값'}을(를) {p.field === 'label' ? p.value : day(p.value)}(으)로 말씀하셨어요. 바꾸려면 그 값을 넣어 다시 조회해 주세요.
    </span>)}
  </li>;
}

export function MemoryPanel() {
  const {authEnabled, user} = useApp();
  const [memory, setMemory] = useState<MemoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [allStep, setAllStep] = useState<'idle' | 'confirm' | 'busy'>('idle');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  // 실제 모드는 로그인한 사람만 기억이 있다. 데모 모드는 가공 예시를 보여 준다
  const viewable = !isLive || (authEnabled && !!user);
  const deletable = isLive && authEnabled && !!user;

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try { setMemory(await getMemory()); }
    catch (e) { setError(e instanceof Error ? e.message : '기억을 불러오지 못했습니다.'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (viewable) void load(); }, [viewable, load]);

  async function removeOne(id: string) {
    setBusyId(id); setError(''); setMessage('');
    try { await deleteMemoryItem(id); setMessage('메모 한 줄을 지웠습니다.'); setConfirmId(null); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : '지우지 못했습니다.'); }
    finally { setBusyId(null); }
  }

  async function removeAll() {
    setAllStep('busy'); setError(''); setMessage('');
    try { const r = await deleteAllMemory(); setMessage(`기억 ${r.deleted}건을 지웠습니다.`); setAllStep('idle'); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : '지우지 못했습니다.'); setAllStep('confirm'); }
  }

  const about = memory?.items.filter(i => i.section === 'about') ?? [];
  const perCargo = memory?.items.filter(i => i.section === 'cargo') ?? [];
  const groups = [...new Set(perCargo.map(i => i.cargo_name ?? '지난 화물'))];

  function itemRow(item: MemoryItem) {
    const text = itemText(item);
    return <li key={item.id} className="memory-item">
      <span><small>{KIND_LABELS[item.kind]}</small>{text}{item.noted_at && <em> · {day(item.noted_at).slice(5)}</em>}</span>
      {deletable && (confirmId === item.id
        ? <span className="danger-actions">
            <button type="button" className="button danger" onClick={() => void removeOne(item.id)} disabled={busyId === item.id}>
              {busyId === item.id ? <LoaderCircle size={14} className="spin"/> : <Trash2 size={14}/>}지우기</button>
            <button type="button" className="button secondary" onClick={() => setConfirmId(null)} disabled={busyId === item.id}>취소</button>
          </span>
        : <button type="button" className="button secondary" onClick={() => { setConfirmId(item.id); setMessage(''); }}
            aria-label={`이 메모 지우기: ${KIND_LABELS[item.kind]} ${text}`}>지우기</button>)}
    </li>;
  }

  return <section className="account-panel memory-panel" aria-labelledby="memory-title">
    <SectionTitle label="내 기억" kicker="WHAT MARVIA REMEMBERS" side={<Brain size={22}/>}/>
    <span id="memory-title" className="sr-only">내 기억</span>
    <p className="muted">조회하고 대화한 내용 중 다시 쓸 만한 것만 기억합니다. 받아야 하는 날, 할 일, 거래처 같은 것들이에요.
      배 이름·입항일·통관 단계는 조회할 때마다 새로 확인하므로 기억하지 않습니다.</p>
    {!viewable ? <p className="muted account-off">{!authEnabled
      ? '이 서버는 로그인이 꺼져 있어 기억을 만들지 않습니다.'
      : '로그인하면 Marvia가 기억한 내용을 보고 지울 수 있습니다.'}</p>
    : <>
      {!isLive && <p className="help-text"><span className="subtle-badge">가공 예시</span> 데모 모드라 실제 기억이 아닙니다. 지우기는 실제 모드에서만 됩니다.</p>}
      {loading && !memory && <p className="muted"><LoaderCircle size={14} className="spin"/> 기억을 불러오는 중</p>}
      {memory && !memory.available && <p className="muted">지금은 기억 저장소에 연결하지 못했습니다. 잠시 뒤 다시 열어 주세요.</p>}
      {memory?.full && <p role="status" className="memory-full">메모장이 가득 찼어요. 지울 메모를 골라 정리해 주세요. 정리하기 전에는 새 메모를 저장하지 않습니다.</p>}
      {memory && memory.available && memory.items.length === 0 && memory.cargo.length === 0 && <p className="muted">아직 기억한 것이 없습니다.</p>}
      {memory && memory.cargo.length > 0 && <div className="memory-block"><h3>기억한 화물</h3>
        <ul className="memory-list">{memory.cargo.map(c => <CargoRow key={`${c.bl_masked}-${c.status}-${c.last_checked_at}`} c={c}/>)}</ul></div>}
      {about.length > 0 && <div className="memory-block"><h3>이 사람에 대해</h3><ul className="memory-list">{about.map(itemRow)}</ul></div>}
      {groups.map(g => <div className="memory-block" key={g}><h3>화물별 · {g}</h3>
        <ul className="memory-list">{perCargo.filter(i => (i.cargo_name ?? '지난 화물') === g).map(itemRow)}</ul></div>)}
      {deletable && memory && (memory.items.length > 0 || memory.cargo.length > 0) && <div className="danger-row">
        <div><h3><Trash2 size={16}/>기억 모두 지우기</h3><p>메모와 기억한 화물을 모두 지웁니다. 조회 기록과 계정은 남습니다. 되돌릴 수 없습니다.</p></div>
        {allStep === 'idle'
          ? <button type="button" className="button secondary" onClick={() => { setAllStep('confirm'); setMessage(''); }}>모두 지우기</button>
          : <div className="danger-actions">
              <button type="button" className="button danger" onClick={() => void removeAll()} disabled={allStep === 'busy'}>
                {allStep === 'busy' ? <LoaderCircle size={15} className="spin"/> : <Trash2 size={15}/>}모두 지우기</button>
              <button type="button" className="button secondary" onClick={() => setAllStep('idle')} disabled={allStep === 'busy'}>취소</button>
            </div>}
      </div>}
    </>}
    {message && <p role="status" className="account-message">{message}</p>}
    {error && <p role="alert" className="request-error">{error}</p>}
  </section>;
}
