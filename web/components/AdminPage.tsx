'use client';
/** 관리 탭 (docs/specs/operator-admin.md). 운영자만 들어온다. 한 페이지에 "고객 관리"와 "운영자" 두 탭.
 *
 * 고객 관리: 서버가 가려 준 이메일·이름, 가입일, 마지막 로그인만 보여 준다. 원문은 받지도 않는다.
 * 시안 4-6·4-7: 요약 숫자 → 목록 → 선택한 고객의 작업 카드(표 아래) → 작업 이력. 행 버튼은 툴팁 달린 아이콘 버튼이고 강제 탈퇴는 오른쪽 끝에 색을 달리해 따로 둔다.
 * 표와 숫자는 흰 상자에 넣지 않고 배경 위에 선으로만 나눈다 (폴리시: 상자 줄이기).
 * 운영자: 이메일로 등록, 목록에서 해지(화면 안에서 한 번 더 확인), 아래에 누가 언제 등록·해지했는지 이력.
 * 운영자가 아닌 사람이 주소로 들어오면 안내만 한다. 데이터는 서버가 403으로 막는다 (EC-01).
 */
import {useCallback, useEffect, useMemo, useState, type FormEvent} from 'react';
import {Eye, LoaderCircle, Pause, Pencil, Play, Search, ShieldUser, UserRoundMinus, UserRoundX} from 'lucide-react';
import {CustomerActions, type CustomerMode} from './CustomerActions';
import {useApp} from './AppProvider';
import {getAdminActions, getCustomers, getOperators, grantOperator, isLive, revokeOperator} from '@/lib/api';
import {dateTime} from '@/lib/format';
import type {ActionItem, CustomersResponse, OperatorsResponse} from '@/lib/types';

type Tab = 'customers' | 'operators';
const DAY_MS = 86_400_000;
const ACTION_LABELS: Record<ActionItem['action'], string> = {unmask: '마스킹 해제', customer_update: '수정', customer_delete: '강제 탈퇴', customer_suspend: '일시 정지', customer_resume: '정지 해제'};

export function AdminPage() {
  const {isOperator, authReady, meReady} = useApp();
  const [tab, setTab] = useState<Tab>('customers');

  // 운영자 여부(GET /api/me)를 받기 전에는 판단하지 않는다. 받기 전 isOperator는 false라 운영자에게도
  // "운영자만 볼 수 있는 화면"이 잠깐 보였다 (UI 점검 F12, OperatorOnly와 같은 조건)
  if (!authReady || !meReady) return <div className="page"><div className="initial-loading" role="status"><div className="loading-orbit"/><strong>권한을 확인하고 있어요.</strong></div></div>;
  if (!isOperator) return <div className="page"><div className="empty-state admin-denied"><ShieldUser size={34} strokeWidth={1.2}/><h2>운영자만 볼 수 있는 화면이에요.</h2><p>권한이 필요하면 기존 운영자에게 등록을 요청해 주세요.</p></div></div>;

  return <div className="page adm-page">
    <div className="page-heading adm-heading">
      <div><span className="eyebrow">운영자</span><h1>{tab === 'customers' ? '고객 관리' : '운영자 관리'}</h1>
        <p>{tab === 'customers' ? '가려진 정보로 고객 상태를 확인하고 필요한 작업을 기록해요.' : '운영자 등록·해지와 권한 변경 이력을 확인해요.'}</p></div>
    </div>
    <div className="adm-tabs" role="tablist" aria-label="관리 메뉴">
      <button role="tab" aria-selected={tab === 'customers'} className={tab === 'customers' ? 'active' : ''} onClick={() => setTab('customers')}>고객 관리</button>
      <button role="tab" aria-selected={tab === 'operators'} className={tab === 'operators' ? 'active' : ''} onClick={() => setTab('operators')}>운영자 관리</button>
    </div>
    {tab === 'customers' ? <CustomersPanel/> : <OperatorsPanel/>}
    {!isLive && <div className="info-note adm-note">체험 모드의 고객·운영자는 예시예요. 등록·해지는 실제 서비스에서만 할 수 있어요.</div>}
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
    getCustomers().then(setData).catch(e => setError(e instanceof Error ? e.message : '고객 목록을 불러오지 못했어요.'));
    getAdminActions().then(setActions).catch(() => setActions([]));
  }, []);
  useEffect(reload, [reload]);
  const refreshActions = useCallback(() => { getAdminActions().then(setActions).catch(() => {}); }, []);
  const close = useCallback(() => { setOpen(null); refreshActions(); }, [refreshActions]);

  // 고객 검색은 전화번호 뒷 4자리로 한다 (전화로 문의한 고객을 찾는 일이 많다). 목록에는 가린 번호
  // (010-****-1234)만 오고 뒷 4자리는 보이므로 화면에서 끝자리를 비교한다. 숫자가 아닌 글자를 넣으면 예전처럼 이메일 앞부분으로 찾는다
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return data?.items ?? [];
    const digits = q.replace(/\D/g, '');
    const byPhone = /^[\d\s-]+$/.test(q) && digits.length > 0;
    return (data?.items ?? []).filter(c => byPhone
      ? (c.phone_masked ?? '').replace(/\D/g, '').endsWith(digits)
      : (c.email_masked ?? '').toLowerCase().includes(q));
  }, [data, query]);
  // 최근 7일 수치는 지금 시각 기준으로 화면에서 센다. 서버 집계가 아니다
  const now = Date.now();
  const recent = (v: string | null) => !!v && now - new Date(v).valueOf() <= 7 * DAY_MS;
  const stats = data ? [
    ['전체 고객', data.total],
    ['최근 7일 가입', data.items.filter(c => recent(c.created_at)).length],
    ['최근 7일 로그인', data.items.filter(c => recent(c.last_sign_in_at)).length],
    ['정보 미입력', data.items.filter(c => !c.profile_complete).length],
    ['정지', data.items.filter(c => c.is_suspended).length],
  ] as const : null;

  const openCustomer = open ? data?.items.find(c => c.user_id === open.id) ?? null : null;
  const blank = [['전체 고객', null], ['최근 7일 가입', null], ['최근 7일 로그인', null], ['정보 미입력', null], ['정지', null]] as const;

  return <section aria-label="고객 관리">
    <div className="adm-stats">{(stats ?? blank).map(([label, value]) =>
      <div key={label} className="adm-stat"><span>{label}</span><strong>{value ?? '-'}<small>명</small></strong></div>)}</div>

    <div className="adm-search-row">
      <div className="adm-search"><Search size={18}/><input id="adm-search-input" aria-label="전화번호 뒷 4자리 또는 이메일로 고객 검색" inputMode="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="고객 검색 (전화번호 뒷 4자리)"/></div>
      <span className="adm-count-total">총 {data?.total ?? '-'}명</span>
    </div>

    <div className="adm-list">
      {error && <p role="alert" className="request-error">{error}</p>}
      {!data && !error ? <div className="empty-state"><LoaderCircle className="spin"/><h2>고객 목록을 불러오고 있어요.</h2></div>
      : data && <div className="table-scroll adm-table adm-customers" role="region" aria-label="고객 목록" tabIndex={0}><table>
        <thead><tr><th>이름</th><th>이메일</th><th>전화</th><th>주소</th><th>가입일 · 최근 로그인</th><th>구분 · 상태</th><th>작업</th></tr></thead>
        <tbody>{rows.map(c => <tr key={c.user_id} className={open?.id === c.user_id ? 'row-open' : ''}>
          <td className="adm-name" data-label="이름">{c.name_masked ?? '-'}</td>
          <td data-label="이메일">{c.email_masked ?? '없음'}</td>
          <td className="adm-sub" data-label="전화">{c.phone_masked ?? (c.profile_complete ? '확인 불가' : '미입력')}</td>
          <td className="adm-sub adm-wrap" data-label="주소">{c.address_masked ?? (c.profile_complete ? '확인 불가' : '미입력')}</td>
          <td className="adm-sub" data-label="가입일 · 로그인"><span className="adm-dates">{dateTime(c.created_at)}<small>{c.last_sign_in_at ? dateTime(c.last_sign_in_at) : '로그인한 적 없음'}</small></span></td>
          {/* 정지는 신호등 색이 아니라 굵은 테두리 칩으로 (순항·주의·긴급 전용 색 규칙) */}
          <td data-label="구분 · 상태"><div className="adm-chips">{c.is_operator ? <span className="adm-chip strong">운영자</span> : !c.is_suspended && <span className="adm-role">고객</span>}{c.is_suspended && <span className="adm-chip suspended">정지</span>}</div></td>
          <td data-label="작업"><div className="adm-actions">
            <div className="adm-act-group">{([['unmask', '마스킹 해제', Eye], ['edit', '수정', Pencil], ['suspend', c.is_suspended ? '정지 해제' : '일시 정지', c.is_suspended ? Play : Pause]] as const).map(([mode, label, Icon]) => {
              const blocked = mode === 'suspend' && !c.is_suspended && c.is_operator;
              return <button key={mode} type="button" className="adm-icon" aria-label={`${c.email_masked ?? '고객'} ${label}`} title={blocked ? `${label}: 운영자 계정은 운영자 해지 뒤에 할 수 있어요` : label}
                aria-expanded={open?.id === c.user_id && open.mode === mode} disabled={!isLive || blocked}
                onClick={() => { setMessage(''); setOpen(o => o?.id === c.user_id && o.mode === mode ? null : {id: c.user_id, mode}); }}><Icon size={18} strokeWidth={1.75}/></button>;
            })}</div>
            {/* 강제 탈퇴는 수정 버튼들과 떨어진 오른쪽 끝, 빨간색 */}
            <button type="button" className="adm-icon adm-icon-danger" aria-label={`${c.email_masked ?? '고객'} 탈퇴`} title={c.is_operator ? '강제 탈퇴: 운영자 계정은 운영자 해지 뒤에 할 수 있어요' : '강제 탈퇴'}
              aria-expanded={open?.id === c.user_id && open.mode === 'delete'} disabled={!isLive || c.is_operator}
              onClick={() => { setMessage(''); setOpen(o => o?.id === c.user_id && o.mode === 'delete' ? null : {id: c.user_id, mode: 'delete'}); }}><UserRoundX size={18} strokeWidth={1.75}/></button>
          </div></td>
        </tr>)}</tbody></table>
        {!rows.length && <div className="empty-state"><Search/><h2>조건에 맞는 고객이 없어요.</h2></div>}
      </div>}
      {message && <p role="status" className="account-message table-message">{message}</p>}
    </div>

    {/* 선택한 고객의 작업 카드: 시안 4-6처럼 표 아래에 펼친다 */}
    {open && openCustomer && <CustomerActions key={`${open.id}-${open.mode}`} customer={openCustomer} mode={open.mode} onClose={close} onLogged={refreshActions} onDone={msg => { setMessage(msg); setOpen(null); reload(); }}/>}

    <section className="adm-audit">
      <div className="adm-section-head"><h2>최근 작업 이력</h2><span>최근 {actions.length}건</span></div>
      <div className="table-scroll adm-table adm-log" role="region" aria-label="고객 작업 이력" tabIndex={0}><table>
        <thead><tr><th>시각</th><th>작업</th><th>대상</th><th>처리한 운영자</th><th>사유</th></tr></thead>
        <tbody>{actions.map((a, i) => <tr key={`${a.created_at}-${i}`}>
          <td data-label="시각">{dateTime(a.created_at)}</td>
          <td data-label="작업"><span className="adm-chip">{ACTION_LABELS[a.action]}</span></td>
          <td data-label="대상">{a.target_email_masked ?? a.target_user_id}</td>
          <td data-label="처리한 운영자">{a.actor_email ?? a.actor_user_id}</td>
          <td className="adm-wrap adm-reason" data-label="사유">{a.reason ?? '-'}</td>
        </tr>)}</tbody></table>
        {!actions.length && <div className="empty-state"><ShieldUser/><h2>아직 작업 이력이 없어요.</h2></div>}
      </div>
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
    getOperators().then(setData).catch(e => setError(e instanceof Error ? e.message : '운영자 목록을 불러오지 못했어요.'));
  }, []);

  async function run(action: () => Promise<OperatorsResponse>, done: string) {
    setBusy(true); setError(''); setMessage('');
    try { setData(await action()); setMessage(done); }
    catch (e) { setError(e instanceof Error ? e.message : '처리하지 못했어요.'); }
    finally { setBusy(false); setConfirming(null); }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const value = email.trim().toLowerCase();
    // 서버(normalize_email)와 같은 정도의 형식 검사. 최종 판단은 서버가 한다
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value)) { setError('이메일 형식을 확인해 주세요.'); return; }
    void run(() => grantOperator(value), `${value}을(를) 운영자로 등록했어요. 그 계정으로 로그인하면 관리 메뉴가 보여요.`).then(() => setEmail(''));
  }

  const me = user?.email?.toLowerCase();

  return <section aria-label="운영자" className="admin-operators">
    <div className="adm-grid">
      <section className="adm-box">
        <div className="adm-box-head"><h2>활성 운영자</h2><span className="adm-count-total">{data?.operators.length ?? '-'}명</span></div>
        {!data ? <div className="empty-inline"><LoaderCircle size={16} className="spin"/>불러오는 중</div>
        : <ul className="adm-op-list">{data.operators.map(o => <li key={o.email}>
            <div className="adm-op-row">
              <div className="adm-op-who"><div><strong>{o.email}</strong>{o.email === me && <span className="adm-chip strong">나</span>}</div>
                <small>{o.granted_by === 'bootstrap' ? '최초 등록(초기 설정)' : o.granted_by_email ? `${o.granted_by_email}이(가) 등록` : '운영자가 등록'} · {dateTime(o.granted_at)}</small></div>
              {o.email === me ? <span className="adm-self">본인은 해지할 수 없어요</span>
              : confirming !== o.email && <button type="button" className="adm-icon adm-icon-danger" aria-label={`${o.email} 운영자 해지`} title="운영자 해지" disabled={busy || !isLive} onClick={() => setConfirming(o.email)}><UserRoundMinus size={18} strokeWidth={1.75}/></button>}
            </div>
            {/* [취소][해지] 순서: 되돌리는 쪽이 왼쪽, 위험한 쪽이 오른쪽 (4-7 결정) */}
            {o.email !== me && confirming === o.email && <div className="adm-confirm"><span>해지할까요?</span>
              <button className="button secondary" disabled={busy} onClick={() => setConfirming(null)}>취소</button>
              <button className="button danger" disabled={busy || !isLive} onClick={() => void run(() => revokeOperator(o.email), `${o.email}의 운영자 권한을 해지했어요.`)}>{busy ? <LoaderCircle size={14} className="spin"/> : null}해지</button></div>}
          </li>)}</ul>}
      </section>
      <section className="adm-card adm-box adm-box-form">
        <div className="adm-box-head"><h2>운영자 등록</h2></div>
        <p className="adm-hint">아직 가입하지 않은 사람도 미리 등록할 수 있어요.</p>
        <form onSubmit={submit} className="adm-grant" noValidate>
          <div className="form-field"><label htmlFor="grant-email">구글 로그인 이메일</label>
            <input id="grant-email" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="name@example.com" autoComplete="off" disabled={busy || !isLive}/></div>
          <button className="button primary" disabled={busy || !email.trim() || !isLive}>{busy ? <LoaderCircle size={15} className="spin"/> : null}운영자 등록</button>
        </form>
        {message && <p role="status" className="account-message">{message}</p>}
        {error && <p role="alert" className="request-error">{error}</p>}
      </section>
    </div>
    <section className="adm-audit">
      <div className="adm-section-head"><h2>운영자 등록·해지 이력</h2><span>최근 {data?.audit.length ?? 0}건</span></div>
      <div className="table-scroll adm-table adm-log" role="region" aria-label="권한 변경 이력" tabIndex={0}><table>
        <thead><tr><th>시각</th><th>동작</th><th>대상 이메일</th><th>처리한 사람</th></tr></thead>
        <tbody>{(data?.audit ?? []).map((a, i) => <tr key={`${a.created_at}-${i}`}>
          <td data-label="시각">{dateTime(a.created_at)}</td>
          <td data-label="동작"><span className={`adm-chip ${a.action === 'grant' ? '' : 'strong'}`}>{a.action === 'grant' ? '등록' : '해지'}</span></td>
          <td data-label="대상 이메일">{a.target_email}</td>
          <td data-label="처리한 사람">{a.actor_user_id === 'bootstrap' ? '초기 설정' : a.actor_email ?? a.actor_user_id}</td>
        </tr>)}</tbody></table>
        {data && !data.audit.length && <div className="empty-state"><ShieldUser/><h2>아직 이력이 없어요.</h2></div>}
      </div>
    </section>
  </section>;
}
