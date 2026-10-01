'use client';
/** 관리 탭 (docs/specs/operator-admin.md). 운영자만 들어온다. 한 페이지에 "고객 관리"와 "운영자" 두 탭.
 *
 * 고객 관리: 서버가 가려 준 이메일·이름, 가입일, 마지막 로그인만 보여 준다. 원문은 받지도 않는다.
 * 운영자: 이메일로 등록, 목록에서 해지(화면 안에서 한 번 더 확인), 아래에 누가 언제 등록·해지했는지 이력.
 * 운영자가 아닌 사람이 주소로 들어오면 안내만 한다. 데이터는 서버가 403으로 막는다 (EC-01).
 */
import {Fragment, useCallback, useEffect, useMemo, useState, type FormEvent} from 'react';
import {Eye, LoaderCircle, PencilLine, Search, ShieldCheck, ShieldUser, UserPlus, UserRoundMinus, UserRoundX, Users} from 'lucide-react';
import {CustomerActions, type CustomerMode} from './CustomerActions';
import {useApp} from './AppProvider';
import {SectionTitle} from './Shared';
import {getAdminActions, getCustomers, getOperators, grantOperator, isLive, revokeOperator} from '@/lib/api';
import {dateTime} from '@/lib/format';
import type {ActionItem, CustomersResponse, OperatorsResponse} from '@/lib/types';

type Tab = 'customers' | 'operators';
const DAY_MS = 86_400_000;
const ACTION_LABELS: Record<ActionItem['action'], string> = {unmask: '마스킹 해제', customer_update: '수정', customer_delete: '강제 탈퇴'};

export function AdminPage() {
  const {isOperator, authReady} = useApp();
  const [tab, setTab] = useState<Tab>('customers');

  if (!authReady) return <div className="page"><div className="initial-loading" role="status"><div className="loading-orbit"/><strong>권한을 확인하고 있어요.</strong></div></div>;
  if (!isOperator) return <div className="page"><div className="empty-state admin-denied"><ShieldUser size={34} strokeWidth={1.2}/><h2>운영자만 볼 수 있는 화면입니다.</h2><p>권한이 필요하면 기존 운영자에게 등록을 요청하세요.</p></div></div>;

  return <div className="page">
    <div className="page-heading">
      <div><span className="eyebrow">OPERATIONS DESK</span><h1>사람과 권한을 한눈에<span className="accent-dot">.</span></h1>
        <p>고객 정보는 가려서 보여 주고, 권한 변경은 모두 기록합니다.</p></div>
      <span className="outline-label"><ShieldCheck size={14}/>운영자 전용</span>
    </div>
    <div className="admin-tabs" role="tablist" aria-label="관리 메뉴">
      <button role="tab" aria-selected={tab === 'customers'} className={tab === 'customers' ? 'active' : ''} onClick={() => setTab('customers')}><Users size={15}/>고객 관리</button>
      <button role="tab" aria-selected={tab === 'operators'} className={tab === 'operators' ? 'active' : ''} onClick={() => setTab('operators')}><ShieldUser size={15}/>운영자</button>
    </div>
    {tab === 'customers' ? <CustomersPanel/> : <OperatorsPanel/>}
    {!isLive && <div className="info-note">데모 모드의 고객·운영자는 가공 예시입니다. 등록·해지는 실제 서버에서만 동작합니다.</div>}
  </div>;
}

function CustomersPanel() {
  const [data, setData] = useState<CustomersResponse | null>(null);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState<{id: string; mode: CustomerMode} | null>(null);
  const [message, setMessage] = useState('');
  const [actions, setActions] = useState<ActionItem[]>([]);

  // 목록과 작업 이력을 같이 다시 읽는다. 수정·탈퇴·마스킹 해제 뒤에 부른다
  const reload = useCallback(() => {
    getCustomers().then(setData).catch(e => setError(e instanceof Error ? e.message : '고객 목록을 불러오지 못했습니다.'));
    getAdminActions().then(setActions).catch(() => setActions([]));
  }, []);
  useEffect(reload, [reload]);
  const close = useCallback(() => { setOpen(null); getAdminActions().then(setActions).catch(() => {}); }, []);

  const rows = useMemo(() => (data?.items ?? []).filter(c =>
    !query.trim() || (c.email_masked ?? '').toLowerCase().includes(query.trim().toLowerCase())), [data, query]);
  // 최근 7일 수치는 지금 시각 기준으로 화면에서 센다. 서버 집계가 아니다
  const now = Date.now();
  const recent = (v: string | null) => !!v && now - new Date(v).valueOf() <= 7 * DAY_MS;
  const stats = data ? [
    ['전체 고객', data.total],
    ['최근 7일 가입', data.items.filter(c => recent(c.created_at)).length],
    ['최근 7일 로그인', data.items.filter(c => recent(c.last_sign_in_at)).length],
    ['정보 미입력', data.items.filter(c => !c.profile_complete).length],
  ] as const : null;

  return <section aria-label="고객 관리">
    <div className="history-stats">{(stats ?? [['전체 고객', null], ['최근 7일 가입', null], ['최근 7일 로그인', null], ['정보 미입력', null]]).map(([label, value]) =>
      <div key={label} className="history-stat neutral"><span>{label}</span><strong>{value ?? '-'}<small>명</small></strong></div>)}</div>
    <div className="history-panel">
      <div className="table-toolbar"><label className="search-history"><Search size={16}/><input aria-label="이메일 앞부분 검색" value={query} onChange={e => setQuery(e.target.value)} placeholder="이메일 앞 두 글자로 검색"/></label></div>
      {error && <p role="alert" className="request-error">{error}</p>}
      {!data && !error ? <div className="empty-state"><LoaderCircle className="spin"/><h2>고객 목록을 불러오는 중입니다.</h2></div>
      : data && <div className="table-scroll" role="region" aria-label="고객 목록" tabIndex={0}><table>
        <thead><tr><th>이메일</th><th>이름</th><th>휴대전화</th><th>주소</th><th>가입일</th><th>마지막 로그인</th><th>구분</th><th>작업</th></tr></thead>
        <tbody>{rows.map(c => <Fragment key={c.user_id}><tr className={open?.id === c.user_id ? 'row-open' : ''}>
          <td className="mono">{c.email_masked ?? '없음'}</td><td>{c.name_masked ?? '-'}</td>
          <td className="mono">{c.phone_masked ?? (c.profile_complete ? '확인 불가' : '미입력')}</td><td>{c.address_masked ?? (c.profile_complete ? '확인 불가' : '미입력')}</td>
          <td className="mono">{dateTime(c.created_at)}</td>
          <td className="mono">{c.last_sign_in_at ? dateTime(c.last_sign_in_at) : '로그인 기록 없음'}</td>
          <td>{c.is_operator ? <span className="role-chip operator"><ShieldCheck size={12}/>운영자</span> : <span className="role-chip">고객</span>}</td>
          <td><div className="row-buttons">
            {([['unmask', Eye, '마스킹 해제'], ['edit', PencilLine, '수정'], ['delete', UserRoundX, '탈퇴']] as const).map(([mode, Icon, label]) =>
              <button key={mode} type="button" className={`icon-button ${mode === 'delete' ? 'danger-icon' : ''}`} aria-label={`${c.email_masked ?? '고객'} ${label}`} title={label}
                aria-expanded={open?.id === c.user_id && open.mode === mode} disabled={!isLive || (mode === 'delete' && c.is_operator)}
                onClick={() => { setMessage(''); setOpen(o => o?.id === c.user_id && o.mode === mode ? null : {id: c.user_id, mode}); }}><Icon size={15}/></button>)}
          </div></td>
        </tr>
        {open?.id === c.user_id && <tr className="action-row"><td colSpan={8}>
          <CustomerActions customer={c} mode={open.mode} onClose={close} onDone={msg => { setMessage(msg); setOpen(null); reload(); }}/>
        </td></tr>}</Fragment>)}</tbody></table>
        {!rows.length && <div className="empty-state"><Search/><h2>조건에 맞는 고객이 없습니다.</h2></div>}
      </div>}
      {message && <p role="status" className="account-message table-message">{message}</p>}
      <div className="table-bottom"><span>{rows.length}명 표시</span><span>원문은 마스킹 해제(사유서)로만 봅니다. 운영자 계정은 운영자 해지 뒤에 탈퇴시킬 수 있습니다.</span></div>
    </div>
    <section className="history-panel admin-audit">
      <div className="table-toolbar"><SectionTitle label="고객 작업 이력" kicker="CUSTOMER ACTIONS"/></div>
      <div className="table-scroll" role="region" aria-label="고객 작업 이력" tabIndex={0}><table>
        <thead><tr><th>시각</th><th>작업</th><th>대상</th><th>처리한 운영자</th><th>사유</th></tr></thead>
        <tbody>{actions.map((a, i) => <tr key={`${a.created_at}-${i}`}>
          <td className="mono">{dateTime(a.created_at)}</td>
          <td><span className={`role-chip ${a.action === 'customer_delete' ? 'revoked' : a.action === 'unmask' ? 'unmask' : 'operator'}`}>{ACTION_LABELS[a.action]}</span></td>
          <td className="mono">{a.target_email_masked ?? a.target_user_id}</td>
          <td className="mono">{a.actor_email ?? a.actor_user_id}</td>
          <td className="reason-cell">{a.reason ?? '-'}</td>
        </tr>)}</tbody></table>
        {!actions.length && <div className="empty-state"><ShieldUser/><h2>아직 작업 기록이 없습니다.</h2></div>}
      </div>
      <div className="table-bottom"><span>최근 {actions.length}건</span><span>이력은 지우거나 고칠 수 없습니다.</span></div>
    </section>
  </section>;
}

function OperatorsPanel() {
  const {user} = useApp();
  const [data, setData] = useState<OperatorsResponse | null>(null);
  const [error, setError] = useState('');
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [confirming, setConfirming] = useState<string | null>(null);

  useEffect(() => {
    getOperators().then(setData).catch(e => setError(e instanceof Error ? e.message : '운영자 목록을 불러오지 못했습니다.'));
  }, []);

  async function run(action: () => Promise<OperatorsResponse>, done: string) {
    setBusy(true); setError(''); setMessage('');
    try { setData(await action()); setMessage(done); }
    catch (e) { setError(e instanceof Error ? e.message : '처리하지 못했습니다.'); }
    finally { setBusy(false); setConfirming(null); }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const value = email.trim().toLowerCase();
    // 서버(normalize_email)와 같은 정도의 형식 검사. 최종 판단은 서버가 한다
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value)) { setError('이메일 형식을 확인해 주세요.'); return; }
    void run(() => grantOperator(value), `${value}을(를) 운영자로 등록했습니다. 그 계정으로 로그인하면 관리 탭이 보입니다.`).then(() => setEmail(''));
  }

  const me = user?.email?.toLowerCase();

  return <section aria-label="운영자" className="admin-operators">
    <div className="admin-grid">
      <section className="admin-card">
        <SectionTitle label="신규 운영자 등록" kicker="GRANT ACCESS" side={<UserPlus size={20}/>}/>
        <form onSubmit={submit} className="grant-form" noValidate>
          <div className="form-field"><label htmlFor="grant-email">구글 로그인 이메일</label>
            <input id="grant-email" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="name@example.com" autoComplete="off" disabled={busy || !isLive}/></div>
          <button className="button primary" disabled={busy || !email.trim() || !isLive}>{busy ? <LoaderCircle size={15} className="spin"/> : <UserPlus size={15}/>}등록</button>
        </form>
        <p className="help-text">아직 가입하지 않은 사람도 미리 등록할 수 있습니다. 등록과 해지는 처리한 운영자와 시각이 이력에 남습니다.</p>
        {message && <p role="status" className="account-message">{message}</p>}
        {error && <p role="alert" className="request-error">{error}</p>}
      </section>
      <section className="admin-card">
        <SectionTitle label="활성 운영자" kicker="ACTIVE OPERATORS" side={<span className="subtle-badge">{data?.operators.length ?? '-'}명</span>}/>
        {!data ? <div className="empty-inline"><LoaderCircle size={16} className="spin"/>불러오는 중</div>
        : <ul className="operator-list">{data.operators.map(o => <li key={o.email}>
            <div><strong className="mono">{o.email}</strong>{o.email === me && <span className="role-chip operator">나</span>}
              <small>{o.granted_by === 'bootstrap' ? '최초 등록(스크립트)' : '운영자가 등록'} · {dateTime(o.granted_at)}</small></div>
            {o.email === me ? <span className="muted self-note">본인은 해지 불가</span>
            : confirming === o.email
              ? <div className="danger-actions"><button className="button danger" disabled={busy || !isLive} onClick={() => void run(() => revokeOperator(o.email), `${o.email}의 운영자 권한을 해지했습니다.`)}>{busy ? <LoaderCircle size={14} className="spin"/> : <UserRoundMinus size={14}/>}해지</button><button className="button secondary" disabled={busy} onClick={() => setConfirming(null)}>취소</button></div>
              : <button className="button secondary danger-outline" disabled={busy || !isLive} onClick={() => setConfirming(o.email)}>해지</button>}
          </li>)}</ul>}
      </section>
    </div>
    <section className="history-panel admin-audit">
      <div className="table-toolbar"><SectionTitle label="권한 변경 이력" kicker="AUDIT TRAIL"/></div>
      <div className="table-scroll" role="region" aria-label="권한 변경 이력" tabIndex={0}><table>
        <thead><tr><th>시각</th><th>동작</th><th>대상</th><th>처리한 운영자</th></tr></thead>
        <tbody>{(data?.audit ?? []).map((a, i) => <tr key={`${a.created_at}-${i}`}>
          <td className="mono">{dateTime(a.created_at)}</td>
          <td><span className={`role-chip ${a.action === 'grant' ? 'operator' : 'revoked'}`}>{a.action === 'grant' ? '등록' : '해지'}</span></td>
          <td className="mono">{a.target_email}</td>
          <td className="mono">{a.actor_user_id === 'bootstrap' ? '스크립트(bootstrap)' : a.actor_email ?? a.actor_user_id}</td>
        </tr>)}</tbody></table>
        {data && !data.audit.length && <div className="empty-state"><ShieldUser/><h2>아직 기록이 없습니다.</h2></div>}
      </div>
      <div className="table-bottom"><span>최근 {data?.audit.length ?? 0}건</span><span>이력은 지우거나 고칠 수 없습니다.</span></div>
    </section>
  </section>;
}
