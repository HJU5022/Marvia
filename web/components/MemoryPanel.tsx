'use client';
/** 설정 화면의 "내 기억" 구역 (docs/specs/memory.md "사용자는 메모장을 보고, 줄 하나 또는 전부 지울 수 있다").
 *
 * GET /api/memory로 Marvia가 기억한 화물과 메모를 보여 주고, 메모 한 줄(DELETE /api/memory/items/{id})이나
 * 메모 전부(DELETE /api/memory)를 지운다. 지우기는 되돌릴 수 없어서 화면 안에서 한 번 더 확인한다 (AccountPanel과 같은 방식).
 * "모두 지우기"는 메모(user_memory)만 지운다. 화물 목록(user_cargo)은 "내 조회 기록 지우기"나 회원 탈퇴 때 지워지고,
 * 끝난 화물은 반출 후 3년 보관 뒤 그 메모와 함께 지워진다 (결정 D2, D3).
 * 키보드·화면 낭독기 사용자를 위해 눌렀을 때 포커스를 옮기고, 결과 글은 늘 있는 status/alert 칸에서만 바꾼다 (focusKeys, 아래).
 * 원본 B/L은 서버가 보내지 않는다. 가린 번호와 이름표만 보인다.
 * 데모 모드는 가공 예시를 보여 주고 지우기는 막는다. 로그인이 꺼진 서버는 기억을 만들지 않는다 (EC-08).
 */
import {useCallback, useEffect, useRef, useState} from 'react';
import {LoaderCircle, Trash2, X, Check} from 'lucide-react';
import {useApp} from './AppProvider';
import {VerdictBadge} from './Shared';
import {deleteAllMemory, deleteMemoryItem, getMemory, isLive} from '@/lib/api';
import {day, verdictLabels} from '@/lib/format';
import type {CargoSummary, MemoryItem, MemoryResponse} from '@/lib/types';

const KIND_LABELS: Record<MemoryItem['kind'], string> = {
  preference: '선호', schedule: '반복 일정', contact: '거래처', worry: '걱정', todo: '할 일',
};
/** 대화에서 들은 새 값 안내. 조사(을/를, 으로/로)는 값에 따라 달라지므로 칸마다 문장을 통째로 쓴다. 값 뒤에는 "라고"만 붙여 받침과 상관없다 */
const PENDING_SENTENCES: Record<string, (value: string) => string> = {
  sale_due_date: v => `대화에서 받아야 하는 날은 ${day(v)}라고 말씀하셨어요.`,
  forwarder_eta: v => `대화에서 포워더가 알려 준 입항일은 ${day(v)}라고 말씀하셨어요.`,
  label: v => `대화에서 이 화물의 이름은 "${v}"라고 말씀하셨어요.`,
};
const PENDING_FALLBACK = (v: string) => `대화에서 새로 말씀하신 값이 있어요: ${v}.`;

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
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric'}).formatToParts(d).map(x => [x.type, x.value]));
  return `${p.month}월 ${p.day}일`;
}

/** 시각을 한국 시각 "10.01 11:00"으로 (kstMonthDay와 같은 기준). 읽을 수 없으면 빈 글자 */
function kstMonthDayTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.valueOf())) return '';
  return `${kstMonthDay(iso)} ${new Intl.DateTimeFormat('en-GB', {timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hour12: false}).format(d)}`;
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
  const name = c.label ? `${c.label} · ${c.bl_masked}` : c.bl_masked;
  if (c.status === 'done') return <li className="memory-cargo done"><div className="mc-head"><strong>{c.summary ?? name}</strong><span className="mc-done">끝난 화물</span></div></li>;
  // "여유 N일"은 크게, 신호등 색을 판정 등급에서 따라간다 (순항=초록, 주의=노랑, 긴급=빨강). 값이 없으면 색을 쓰지 않는다
  const slack = c.last_verdict ? margin(c.last_days_margin) : null;
  const rows: [string, React.ReactNode][] = [];
  if (c.sale_due_date) rows.push(['판매 예정일', day(c.sale_due_date)]);
  if (c.forwarder_eta) rows.push(['포워더가 알려 준 입항 예정일', day(c.forwarder_eta)]);
  // 통관 단계는 서버가 저장한 UNI-PASS 단계 이름 그대로 (진행 칸). 시각은 시·분까지 (M4)
  if (c.last_stage) rows.push(['통관 단계', c.last_stage]);
  if (c.last_checked_at && c.last_verdict) rows.push(['마지막 확인', `${kstMonthDayTime(c.last_checked_at)} 판정`]);
  // 보조 정보는 한 줄로 합친다: B/L 종류와 거래 조건
  const sub = [c.bl_type === 'HOUSE' ? 'House B/L' : 'Master B/L', ...conditions(c)].join(' · ');
  return <li className="memory-cargo">
    <div className="mc-head"><strong>{name}</strong>{c.last_verdict ? <VerdictBadge verdict={c.last_verdict}/> : <span className="mc-none">판정 이력 없음</span>}</div>
    <p className="mc-cond">{sub}</p>
    {slack && c.last_verdict && <p className={`memory-slack ${c.last_verdict}`}>{slack}</p>}
    {rows.length > 0 && <dl className="mc-rows">{rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>}
    {c.pending.map(p => <p key={p.field} className="memory-pending">
      {(PENDING_SENTENCES[p.field] ?? PENDING_FALLBACK)(p.value)} 바꾸려면 그 값을 넣어 다시 조회해 주세요.
    </p>)}
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
  // 다음 그림이 그려진 뒤 포커스를 줄 곳. data-focus 이름을 앞에서부터 찾아 처음 있는 것에 준다 (없으면 다음 후보)
  const [focusKeys, setFocusKeys] = useState<string[]>([]);
  const sectionRef = useRef<HTMLElement>(null);

  // 실제 모드는 로그인한 사람만 기억이 있다. 데모 모드는 가공 예시를 보여 준다
  const viewable = !isLive || (authEnabled && !!user);
  const deletable = isLive && authEnabled && !!user;

  // 포커스 옮기기: 누른 버튼이 사라지거나 바뀌면 키보드 사용자는 문서 맨 위로 튕긴다. 그림이 다 그려진 뒤(불러오는 중이 아닐 때) 한 번만 옮긴다
  useEffect(() => {
    if (focusKeys.length === 0 || loading) return;
    for (const key of focusKeys) {
      const el = sectionRef.current?.querySelector<HTMLElement>(`[data-focus="${CSS.escape(key)}"]`);
      if (el) { el.focus(); break; }
    }
    setFocusKeys([]);
  }, [focusKeys, loading, memory, confirmId, allStep]);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try { setMemory(await getMemory()); }
    catch (e) { setError(e instanceof Error ? e.message : '기억을 불러오지 못했어요.'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (viewable) void load(); }, [viewable, load]);

  const about = memory?.items.filter(i => i.section === 'about') ?? [];
  const perCargo = memory?.items.filter(i => i.section === 'cargo') ?? [];
  const groups = [...new Set(perCargo.map(i => i.cargo_name ?? '지난 화물'))];
  // 화면에 보이는 순서의 메모 목록. 지운 뒤 포커스를 줄 이웃 줄을 찾는 데 쓴다
  const ordered = [...about, ...groups.flatMap(g => perCargo.filter(i => (i.cargo_name ?? '지난 화물') === g))];

  async function removeOne(id: string) {
    // 지운 줄의 다음 줄, 없으면 앞 줄의 지우기 버튼, 그것도 없으면 결과 글 칸으로
    const at = ordered.findIndex(i => i.id === id);
    const neighbors = [ordered[at + 1], ordered[at - 1]].filter((i): i is MemoryItem => !!i).map(i => `del-${i.id}`);
    setBusyId(id); setError(''); setMessage('');
    try {
      await deleteMemoryItem(id); setMessage('메모 한 줄을 지웠어요.'); setConfirmId(null);
      await load(); setFocusKeys([...neighbors, 'status']);
    }
    catch (e) { setError(e instanceof Error ? e.message : '지우지 못했어요.'); setFocusKeys([`confirm-${id}`]); }
    finally { setBusyId(null); }
  }

  async function removeAll() {
    setAllStep('busy'); setError(''); setMessage('');
    try {
      const r = await deleteAllMemory(); setMessage(`메모 ${r.deleted}건을 지웠어요. 기억한 화물 목록은 그대로예요.`); setAllStep('idle');
      await load(); setFocusKeys(['all-start', 'status']);
    }
    catch (e) { setError(e instanceof Error ? e.message : '지우지 못했어요.'); setAllStep('confirm'); setFocusKeys(['all-confirm']); }
  }

  function itemRow(item: MemoryItem) {
    const text = itemText(item);
    const label = `${KIND_LABELS[item.kind]} ${text}`;
    return <li key={item.id} className="memory-item">
      <span className="memory-body"><small>{KIND_LABELS[item.kind]}</small><span className="memory-text">{text}</span>{item.noted_at && <em>{day(item.noted_at).slice(5)}</em>}</span>
      {deletable && (confirmId === item.id
        ? <span className="danger-actions">
            <button type="button" className="icon-btn" disabled={busyId === item.id} aria-label="취소" title="취소"
              onClick={() => { setConfirmId(null); setFocusKeys([`del-${item.id}`]); }}><X size={18}/></button>
            <button type="button" className="icon-btn danger" data-focus={`confirm-${item.id}`} aria-label={`이 메모 지우기 확인: ${label}`} title="지우기 확인"
              onClick={() => void removeOne(item.id)} disabled={busyId === item.id}>
              {busyId === item.id ? <LoaderCircle size={18} className="spin"/> : <Check size={18}/>}</button>
          </span>
        : <button type="button" className="icon-btn" data-focus={`del-${item.id}`} aria-label={`이 메모 지우기: ${label}`} title="메모 지우기"
            onClick={() => { setConfirmId(item.id); setMessage(''); setFocusKeys([`confirm-${item.id}`]); }}><Trash2 size={18}/></button>)}
    </li>;
  }

  const empty = memory && memory.available && memory.items.length === 0 && memory.cargo.length === 0;
  return <section ref={sectionRef} className="memory-panel" aria-labelledby="memory-title">
    <span id="memory-title" className="sr-only">기억한 화물</span>
    {!viewable ? <p className="st-note account-off">{!authEnabled
      ? '지금은 로그인 기능이 꺼져 있어 기억을 만들지 않아요.'
      : '로그인하면 Marvia가 기억한 내용을 보고 지울 수 있어요.'}</p>
    : <>
      {!isLive && <p className="st-note">체험 모드라 실제 기억이 아니에요. 지우기는 실제 서비스에서만 할 수 있어요.</p>}
      {loading && !memory && <p className="st-note"><LoaderCircle size={16} className="spin"/> 기억을 불러오는 중</p>}
      {memory && !memory.available && <p className="st-note">지금은 기억을 불러오지 못했어요. 잠시 뒤 다시 열어 주세요.</p>}
      {memory?.full && <p role="status" className="memory-full">메모장이 가득 찼어요. 지울 메모를 골라 정리해 주세요. 정리하기 전에는 새 메모를 저장하지 않아요.</p>}
      {empty && <p className="st-note">아직 기억한 것이 없어요.</p>}
      {memory && memory.available && !empty && <div className="st-cols memory">
        <section className="st-card"><h2>기억한 화물</h2><p className="st-sub">{memory.cargo.length > 0 ? `최근 저장된 화물 ${memory.cargo.length}건` : '기억한 화물이 없어요.'}</p>
          {memory.cargo.length > 0 && <ul className="memory-list cargo-cards">{memory.cargo.map((c, i) => <CargoRow key={`${i}-${c.bl_masked}-${c.status}-${c.last_checked_at ?? ''}`} c={c}/>)}</ul>}</section>
        <section className="st-card"><h2>메모</h2><p className="st-sub">{memory.items.length > 0
          ? `${memory.items.length}개 저장${memory.max_chars ? `, ${memory.used_chars ?? 0}/${memory.max_chars}자 사용` : ''}`
          : '저장된 메모가 없어요.'}</p>
          {about.length > 0 && <div className="memory-block"><h3>나에 대해</h3><ul className="memory-list">{about.map(itemRow)}</ul></div>}
          {groups.map(g => <div className="memory-block" key={g}><h3>화물별 · {g}</h3>
            <ul className="memory-list">{perCargo.filter(i => (i.cargo_name ?? '지난 화물') === g).map(itemRow)}</ul></div>)}
          {deletable && memory.items.length > 0 && <div className="st-danger-row memory-clear">
            <p id="memory-all-desc">메모만 모두 지워요. 기억한 화물 목록은 그대로고, "내 조회 이력 지우기"나 회원 탈퇴 때 함께 지워져요. 되돌릴 수 없어요.</p>
            {allStep === 'idle'
              ? <button type="button" className="button secondary danger-outline" data-focus="all-start" aria-describedby="memory-all-desc"
                  onClick={() => { setAllStep('confirm'); setMessage(''); setFocusKeys(['all-confirm']); }}><Trash2 size={16}/>메모 모두 지우기</button>
              : <div className="danger-actions">
                  <button type="button" className="button secondary" disabled={allStep === 'busy'}
                    onClick={() => { setAllStep('idle'); setFocusKeys(['all-start']); }}>취소</button>
                  <button type="button" className="button danger" data-focus="all-confirm" aria-describedby="memory-all-desc"
                    aria-label={`메모 ${memory.items.length}건 모두 지우기 확인`} onClick={() => void removeAll()} disabled={allStep === 'busy'}>
                    {allStep === 'busy' ? <LoaderCircle size={16} className="spin"/> : <Trash2 size={16}/>}모두 지우기</button>
                </div>}
          </div>}
        </section>
      </div>}
    </>}
    {/* 칸은 처음부터 있고 글만 바뀐다. 나중에 생긴 칸은 화면 낭독기가 읽지 않는 경우가 있다. 비어 있을 때는 CSS(:empty)로 안 보이게 한다 */}
    <p role="status" className="account-message" data-focus="status" tabIndex={-1}>{message}</p>
    <p role="alert" className="request-error">{error}</p>
  </section>;
}
