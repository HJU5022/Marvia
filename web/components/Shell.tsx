'use client';
/** 앱 틀: 왼쪽 사이드바 + 상단 줄 + 본문 + 하단 링크.
 * 사이드바는 위에서 아래로 한 흐름이다: 로고·접기 → "새 대화" → 대화 목록(가장 넓고 스크롤) → 화물 메뉴(접는 묶음) → 운영자 묶음 → Marvia 소개 → 계정 줄.
 * 계정 줄을 누르면 위로 뜨는 작은 창에서 프로필·설정·계정 관리·로그아웃을 연다 (예전 오른쪽 위 아바타 메뉴는 이 창과 겹쳐 뺐다).
 * 접으면 아이콘 줄(rail)이 되고, 펼치면 본문이 밀린다(덮지 않는다). 접기는 이 브라우저에만 기억한다 (localStorage marvia.rail).
 * 900px 이하에서는 사이드바가 왼쪽에서 나오는 서랍이 된다. 상단 줄의 메뉴 버튼으로 연다.
 * 로그인이 켜져 있고 로그인 전이면 사이드바·상단 줄 없이 LoginScreen만 전체 화면으로 보인다.
 * 메뉴는 GET /api/me의 is_operator로 나눈다. 숨김은 편의이고 권한은 서버가 막는다 (OperatorOnly, 관리 API 403). */
import Link from 'next/link';
import {usePathname} from 'next/navigation';
import {useEffect, useRef, useState} from 'react';
import {Boxes, ChartNoAxesCombined, ChevronDown, ChevronsUpDown, CircleUserRound, History, Info, LogOut, Menu, PanelLeftClose, PanelLeftOpen, Plus, Radar, Search, Settings2, ShieldUser, Table2, UserCog, X} from 'lucide-react';
import {LoginScreen} from './LoginScreen';
import {ProfileForm} from './ProfileForm';
import {ConversationList} from './ConversationList';
import {LegalLinks} from './LegalLinks';
import {signOut} from '@/lib/auth';
import {SUSPENDED_MESSAGE} from '@/lib/api';
import {useApp} from './AppProvider';
import {isLive} from '@/lib/api';

// 화물 묶음(접는 메뉴): 감시 화물 · 화물 현황 · 조회 이력.
// "내 화물"은 "/"(대화 화면)로 가서 "새 대화"와 대화 목록과 겹쳤다. 같은 곳으로 가는 길이 셋이면 헷갈려서 뺐다. 대화는 "새 대화"와 목록으로 연다
const cargoMenu = [
  {href: '/watch', label: '감시 화물', icon: Radar},
  {href: '/cargo', label: '화물 현황', icon: Table2},
  {href: '/history', label: '조회 이력', icon: History},
];
// 운영자에게만 보이는 묶음 (docs/specs/operator-admin.md). 숨김은 편의이고 권한은 서버가 막는다
const operatorMenu = [
  {href: '/metrics', label: '평가 지표', icon: ChartNoAxesCombined},
  {href: '/admin', label: '관리', icon: ShieldUser},
];
const aboutItem = {href: '/about', label: 'Marvia 소개', icon: Info};
// 계정 창의 항목. tab은 SettingsPage의 탭 키 (?tab=)
const accountMenu = [
  {tab: 'profile', label: '프로필', icon: CircleUserRound},
  // 설정 탭 이름을 "알림·판정 기준"으로 바꿨으니 계정 창 항목도 같은 이름으로 맞춘다 (탭 키 rules는 그대로)
  {tab: 'rules', label: '알림·판정 기준', icon: Settings2},
  {tab: 'account', label: '계정 관리', icon: UserCog},
];
const cargoPaths = cargoMenu.map(m => m.href);

/** 상단 경로 표시. 메뉴에 안 보이는 화면(운영자가 아닌 사람이 주소로 연 /metrics·/admin)도 제 이름을 보인다 (UI 점검 F16) */
function crumb(path: string, chatTitle?: string) {
  // "/"는 내 화물 메뉴와 같은 주소지만 실제로는 대화 화면이다. "내 화물"로 적으면 화물 목록으로 오해해서 대화 제목(없으면 "대화")을 보인다
  if (path === '/') return chatTitle || '대화';
  if (path === '/settings') return '내 정보와 설정';
  const hit = [...cargoMenu, ...operatorMenu, aboutItem].find(l => l.href === path);
  if (!hit) return 'Marvia';
  // "내 화물" 메뉴가 없어졌으니 앞에 붙이던 "내 화물 / "도 뺀다. 메뉴 이름 그대로 보인다
  return hit.label;
}

export function Shell({children}: {children: React.ReactNode}) {
  const path = usePathname();
  const {data, authEnabled, authReady, user, reset, isOperator, profileComplete, meReady, suspended, conversationsOn, savedId, newConversation, loading, opening, conversations, activeId} = useApp();
  const [convOpen, setConvOpen] = useState(false);  // 접힌 사이드바·40:60 화면에서 대화 목록을 여는 패널. 여는 단추는 채팅 칸 왼쪽 위(page.tsx). 상단바 "대화" 버튼은 사이드바와 겹쳐 뺐다
  const [collapsed, setCollapsed] = useState(false);
  const [narrow, setNarrow] = useState(false);  // 900px 이하: 사이드바가 서랍
  const [drawer, setDrawer] = useState(false);
  const [cargoOpen, setCargoOpen] = useState(false);
  const [menu, setMenu] = useState(false);  // 계정 창
  const accountRef = useRef<HTMLDivElement>(null);

  // 접기: 이 브라우저에만 기억한다 (저장이 막혀도 기본 넓은 메뉴로 동작)
  useEffect(() => { try { setCollapsed(localStorage.getItem('marvia.rail') === 'collapsed'); } catch { /* 저장소를 못 쓰면 넓은 메뉴 */ } }, []);
  function toggleRail() { setCollapsed(c => { const next = !c; try { localStorage.setItem('marvia.rail', next ? 'collapsed' : 'open'); } catch { /* 기억 못 해도 동작은 한다 */ } return next; }); }
  // 좁은 화면 판단은 CSS와 같은 900px. 서랍은 좁을 때만 의미가 있다
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 900px)');
    const on = () => { setNarrow(mq.matches); if (!mq.matches) setDrawer(false); };
    on(); mq.addEventListener('change', on); return () => mq.removeEventListener('change', on);
  }, []);
  // 화면을 옮기면 서랍·계정 창을 닫고, 화물 묶음에 속한 화면이면 그 묶음을 펼친다
  useEffect(() => { setDrawer(false); setMenu(false); if (cargoPaths.includes(path)) setCargoOpen(true); }, [path]);
  // 좁은 화면(900px 이하)이나 접은 메뉴는 사이드바에 대화 목록을 둘 자리가 없다. 상단바 버튼이 여는 패널로 같은 목록을 보인다. Esc로 닫는다
  useEffect(() => { if (!convOpen) return; const k = (e: KeyboardEvent) => { if (e.key === 'Escape') setConvOpen(false); }; window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k); }, [convOpen]);
  // 화면 안(대화 칸 왼쪽 위)의 버튼이 같은 대화 목록 패널을 열도록 이벤트를 듣는다. 40:60 화면에서도 사이드바 목록은 그대로 보인다
  useEffect(() => { const open = () => setConvOpen(true); window.addEventListener('marvia:conversations', open); return () => window.removeEventListener('marvia:conversations', open); }, []);
  // 서랍은 Esc로 닫는다. 계정 창은 Esc와 바깥 클릭으로 닫힌다 (UI 점검 F17). 열려 있을 때만 듣는다
  useEffect(() => {
    if (!drawer && !menu) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setMenu(false); setDrawer(false); } };
    const onDown = (e: PointerEvent) => { if (menu && accountRef.current && !accountRef.current.contains(e.target as Node)) setMenu(false); };
    document.addEventListener('keydown', onKey); document.addEventListener('pointerdown', onDown);
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('pointerdown', onDown); };
  }, [drawer, menu]);

  // 저장된 대화가 있으면 "/"로 가는 링크는 그 대화를 이어서 연다 (conversations 기능)
  const toHref = (h: string) => h === '/' && savedId ? `/?c=${encodeURIComponent(savedId)}` : h;
  // 로그인 확인 전(authReady=false)에는 빈 본문. 로그인 화면이 잠깐 깜빡이지 않게 한다
  const gated = authEnabled && path !== '/about' && (!authReady || !user);
  // 로그인했지만 회원 정보가 없으면 입력 화면 (docs/specs/user-profile.md). 확인 전(meReady=false)에는 빈 본문
  const needProfile = authEnabled && !!user && path !== '/about' && (!meReady || !profileComplete);
  // 정지된 계정은 회원 정보 입력보다 먼저 안내 (operator-admin 일시 정지)
  const blocked = authEnabled && !!user && meReady && suspended && path !== '/about';
  async function logout() { setMenu(false); setDrawer(false); await signOut(); reset(); }

  // 로그인 전·회원 정보 입력·정지 안내는 사이드바와 상단 줄 없이 전체 화면
  if (gated || needProfile || blocked) {
    return <div className="entry-shell"><a className="skip-link" href="#main">본문으로 건너뛰기</a><main id="main" tabIndex={-1}>
      {gated ? (authReady ? <LoginScreen/> : <div className="initial-loading" role="status"><div className="loading-orbit"/><strong>로그인 상태를 확인하고 있어요.</strong></div>)
        : blocked ? <div className="login-page"><section className="login-card" role="alert"><h1>계정이 일시 정지됐어요</h1><p>{SUSPENDED_MESSAGE}</p><button type="button" className="button secondary login-google" onClick={() => void logout()}><LogOut size={15}/>로그아웃</button></section></div>
        : (meReady ? <ProfileForm mode="required"/> : <div className="initial-loading" role="status"><div className="loading-orbit"/><strong>회원 정보를 확인하고 있어요.</strong></div>)}
    </main></div>;
  }

  const rail = collapsed && !narrow;  // 아이콘 줄 모양은 넓은 화면에서만
  const initial = (user?.name ?? user?.email ?? 'M').trim().charAt(0).toUpperCase();
  const item = ({href, label, icon: Icon}: {href: string; label: string; icon: typeof Search}, on: boolean, sub = false) =>
    <Link key={href} href={toHref(href)} className={`sb-item${on ? ' active' : ''}${sub ? ' sub' : ''}`} aria-current={on ? 'page' : undefined} aria-label={label} data-sbtip={label}><Icon size={16} strokeWidth={1.75}/><span>{label}</span></Link>;
  const groupOn = cargoPaths.includes(path);
  const locked = loading || opening;
  function startNew() { if (locked) return; newConversation(); setDrawer(false); }
  // 계정 창 항목: 설정의 해당 탭으로. 이미 설정 화면이면 주소만 바뀌어 탭이 안 따라오므로 이벤트로도 알린다 (SettingsPage가 듣는다)
  function openTab(tab: string) { setMenu(false); setDrawer(false); window.dispatchEvent(new CustomEvent('marvia:settings-tab', {detail: tab})); }

  return <div className={`app-shell${rail ? ' rail-collapsed' : ''}${drawer ? ' sb-open' : ''}`}>
    <a className="skip-link" href="#main">본문으로 건너뛰기</a>
    <aside className="sidebar sb" aria-label="사이드바" {...(narrow && !drawer ? {inert: true} : {})}>
      <div className="sb-head">
        <Link href={toHref('/')} className="sb-brand" aria-label="Marvia 대화"><img src="/brand/marvia-symbol.svg" alt="" width={28} height={28}/><strong>Marvia</strong></Link>
        <button type="button" className="sb-collapse" onClick={toggleRail} aria-label={collapsed ? '메뉴 펼치기' : '메뉴 접기'} aria-expanded={!collapsed} data-sbtip={collapsed ? '메뉴 펼치기' : '메뉴 접기'}>{collapsed ? <PanelLeftOpen size={18} strokeWidth={1.75}/> : <PanelLeftClose size={18} strokeWidth={1.75}/>}</button>
        <button type="button" className="sb-close" onClick={() => setDrawer(false)} aria-label="메뉴 닫기"><X size={18} strokeWidth={1.75}/></button>
      </div>
      <button type="button" className="sb-new" onClick={startNew} disabled={locked} aria-label="새 대화" data-sbtip="새 대화"><Plus size={16} strokeWidth={2}/><span>새 대화</span></button>

      <div className="sb-body">
        {conversationsOn && !rail && <section className="conv-section sb-conv" aria-label="대화"><div className="sb-caption">대화</div><ConversationList onPick={() => setDrawer(false)}/></section>}
        <nav className="sb-nav" aria-label="주 메뉴">
          {rail
            // 접힌 줄: 묶음 머리 없이 아이콘만 세로로. 묶음 사이는 가는 선
            ? <>{cargoMenu.map(l => item(l, path === l.href))}<hr/>{item(aboutItem, path === aboutItem.href)}{isOperator && <><hr/>{operatorMenu.map(l => item(l, path === l.href))}</>}</>
            : <>
              <div className={`sb-group${cargoOpen ? ' open' : ''}`}>
                <button type="button" className={`sb-group-head${groupOn ? ' has-active' : ''}`} aria-expanded={cargoOpen} aria-controls="sb-cargo" onClick={() => setCargoOpen(o => !o)}><Boxes size={16} strokeWidth={1.75}/><span>화물</span><ChevronDown size={14} className="chev"/></button>
                {cargoOpen && <div id="sb-cargo" className="sb-group-items" role="group" aria-label="화물">{cargoMenu.map(l => item(l, path === l.href, true))}</div>}
              </div>
              <hr/>
              {item(aboutItem, path === aboutItem.href)}
              {isOperator && <><hr/><div className="sb-caption">운영자</div>{operatorMenu.map(l => item(l, path === l.href))}</>}
            </>}
        </nav>
      </div>

      <div className="sb-foot" ref={accountRef}>
        {user ? <>
          <button type="button" className="sb-account" aria-haspopup="menu" aria-expanded={menu} aria-label={`${user.email ?? '사용자'} 계정 메뉴`} data-sbtip={user.email ?? '계정'} onClick={() => setMenu(m => !m)}>
            <span className="sb-avatar" aria-hidden="true">{initial}</span><span className="sb-account-name">{user.email ?? user.name ?? '로그인 사용자'}</span><ChevronsUpDown size={14} className="chev"/>
          </button>
          {menu && <div className="sb-pop" role="menu" aria-label="계정">
            <div className="sb-pop-user">{user.email}</div>
            {accountMenu.map(({tab, label, icon: Icon}) => <Link key={tab} href={`/settings?tab=${tab}`} role="menuitem" onClick={() => openTab(tab)}><Icon size={15} strokeWidth={1.75}/>{label}</Link>)}
            <hr/>
            <button type="button" role="menuitem" onClick={() => void logout()}><LogOut size={15} strokeWidth={1.75}/>로그아웃</button>
          </div>}
        </> : <div className="sb-account static"><span className="sb-avatar" aria-hidden="true">{authEnabled ? '?' : 'M'}</span><span className="sb-account-name">{!isLive ? '체험 중' : authEnabled ? '로그인 전' : '접속 중'}</span></div>}
      </div>
    </aside>
    {narrow && drawer && <button type="button" className="sb-backdrop" aria-label="메뉴 닫기" onClick={() => setDrawer(false)}/>}

    <div className="workspace">
      <header className="workspace-bar">
        <button type="button" className="sb-burger" onClick={() => setDrawer(true)} aria-label="메뉴 열기" aria-expanded={drawer}><Menu size={20} strokeWidth={1.75}/></button>
        <span className="sb-crumb">{crumb(path, conversations.find(c => c.id === activeId)?.title)}</span>
        <div className="workspace-meta">
          <span className="port-label">{data.demo.port.name}</span>
          <span className="replay-chip"><span/>{isLive ? '실시간 조회' : '체험 · 예시 데이터'}</span>
        </div>
      </header>
      <main id="main" tabIndex={-1}><div key={path} className="route-fade">{children}</div></main>
      {conversationsOn && convOpen && <div className="conv-overlay"><button type="button" className="conv-backdrop" aria-label="대화 목록 닫기" onClick={() => setConvOpen(false)}/><aside className="conv-sheet" role="dialog" aria-label="대화 목록"><div className="conv-sheet-head"><strong>대화</strong><button type="button" onClick={() => setConvOpen(false)}>닫기</button></div><ConversationList withNew onPick={() => setConvOpen(false)}/></aside></div>}
      <footer className="app-footer"><LegalLinks/></footer>
    </div>
  </div>;
}
