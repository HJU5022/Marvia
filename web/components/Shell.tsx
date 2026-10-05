'use client';
/** 고정 사이드바와 상단 바. 로그인이 켜져 있으면 로그인 전에는 본문 대신 LoginScreen을 보여 준다 (G3, 소개 페이지는 예외).
 * 흰 레일 + 해양 블루 (10-02 개편, web/DESIGN.md). 태블릿에서는 아이콘만 남으므로 링크마다 aria-label로 이름을 유지한다.
 * 메뉴는 GET /api/me의 is_operator로 나눈다. 숨김은 편의이고 권한은 서버가 막는다 (OperatorOnly, 관리 API 403). */
import Link from 'next/link';
import {usePathname} from 'next/navigation';
import {useEffect,useState} from 'react';
import {ArrowUpRight, Boxes, ChartNoAxesCombined, Compass, History, LogOut, MessagesSquare, Settings2, ShieldUser, Waves} from 'lucide-react';
import {LoginScreen} from './LoginScreen';
import {ProfileForm} from './ProfileForm';
import {ConversationList} from './ConversationList';
import {signOut} from '@/lib/auth';
import {SUSPENDED_MESSAGE} from '@/lib/api';
import {useApp} from './AppProvider';
import {isLive} from '@/lib/api';
// operatorOnly: 운영자에게만 보이는 탭 (10-01). 평가 지표는 일반 사용자에게 필요 없는 시스템 품질 화면이다
const links=[{href:'/',label:'내 화물',en:'MY CARGO',icon:Boxes},{href:'/history',label:'조회 이력',en:'HISTORY',icon:History},{href:'/metrics',label:'평가 지표',en:'EVALUATION',icon:ChartNoAxesCombined,operatorOnly:true},{href:'/settings',label:'설정',en:'SETTINGS',icon:Settings2}];
// 운영자에게만 보이는 탭 (docs/specs/operator-admin.md). 숨김은 편의이고 권한은 서버가 막는다
const adminLink={href:'/admin',label:'관리',en:'ADMIN',icon:ShieldUser};
export function Shell({children}:{children:React.ReactNode}) {
 const path=usePathname();const {data,authEnabled,authReady,user,reset,isOperator,profileComplete,meReady,suspended,conversationsOn,savedId}=useApp();const nav=isOperator?[...links,adminLink]:links.filter(l=>!l.operatorOnly);const [menu,setMenu]=useState(false);const [convOpen,setConvOpen]=useState(false);
 // 좁은 화면(900px 이하)은 사이드바가 아이콘만 남아 목록을 둘 자리가 없다. 상단바 버튼이 여는 패널로 같은 목록을 보인다. Esc로 닫는다
 useEffect(()=>{if(!convOpen)return;const k=(e:KeyboardEvent)=>{if(e.key==='Escape')setConvOpen(false);};window.addEventListener('keydown',k);return()=>window.removeEventListener('keydown',k);},[convOpen]);
 // 로그인 확인 전(authReady=false)에는 빈 본문. 로그인 화면이 잠깐 깜빡이지 않게 한다
 const gated=authEnabled&&path!=='/about'&&(!authReady||!user);
 // 로그인했지만 회원 정보가 없으면 입력 화면 (docs/specs/user-profile.md). 확인 전(meReady=false)에는 빈 본문
 const needProfile=authEnabled&&!!user&&path!=='/about'&&(!meReady||!profileComplete);
 // 정지된 계정은 회원 정보 입력보다 먼저 안내 (operator-admin 일시 정지)
 const blocked=authEnabled&&!!user&&meReady&&suspended&&path!=='/about';
 const initial=(user?.name??user?.email??'M').trim().charAt(0).toUpperCase();
 async function logout(){setMenu(false);await signOut();reset();}
 return <div className="app-shell"><a className="skip-link" href="#main">본문으로 건너뛰기</a><aside className="sidebar"><Link href="/" className="brand" aria-label="Marvia 내 화물"><span className="brand-symbol"><Waves size={25}/></span><span>marvia<span className="brand-dot">.</span></span></Link><div className="sidebar-kicker">A CLEARER WAY TO ARRIVE</div><div className="nav-caption">WORKSPACE</div><nav aria-label="주 메뉴">{nav.map(({href,label,en,icon:Icon})=><Link key={href} href={href==='/'&&savedId?`/?c=${encodeURIComponent(savedId)}`:href} className={`nav-link ${path===href?'active':''}`} aria-current={path===href?'page':undefined} aria-label={label}><Icon size={19}/><span>{label}<small>{en}</small></span>{path===href&&<span className="nav-dot"/>}</Link>)}</nav>{conversationsOn&&<section className="conv-section" aria-label="대화"><div className="nav-caption">대화</div><ConversationList/></section>}<div className="sidebar-bottom"><div className="port-stamp"><Compass size={22} strokeWidth={1.4}/><div><span className="eyebrow">BUSAN, KOREA</span>도착지를 넘어,<br/>판단의 근거까지.</div></div><Link className={`about-link ${path==='/about'?'active':''}`} href="/about">Marvia 소개 <ArrowUpRight size={16}/></Link><div className="sidebar-meta"><span className="online-dot"/> {isLive?'실시간 조회':'체험용 예시'}<br/><span className="session-id">{isLive?(user?.email??(authEnabled?'로그인 전':'')):'가공 데이터'}</span></div></div></aside><div className="workspace"><header className="workspace-bar"><span><span className="breadcrumb">워크스페이스</span><span className="slash">/</span>{nav.find(l=>l.href===path)?.label??'Marvia 소개'}</span><div className="workspace-meta">{conversationsOn&&<button type="button" className="conv-toggle" aria-expanded={convOpen} onClick={()=>setConvOpen(true)}><MessagesSquare size={14}/>대화</button>}<span className="port-label">{data.demo.port.name}</span><span className="replay-chip"><span/>{isLive?'실시간 조회':'재생 · 가공 데이터'}</span>{user?<div className="user-menu"><button type="button" className="avatar" aria-label={`${user.email??'사용자'} 계정 메뉴`} aria-expanded={menu} onClick={()=>setMenu(m=>!m)}>{initial}</button>{menu&&<div className="user-popover" role="menu"><span className="user-name">{user.name??'로그인 사용자'}</span><span className="user-email">{user.email}</span><Link href="/settings" role="menuitem" onClick={()=>setMenu(false)}>계정과 기록 관리</Link><button type="button" role="menuitem" onClick={()=>void logout()}><LogOut size={14}/>로그아웃</button></div>}</div>:<span className="avatar" aria-label={authEnabled?'로그인 전':'데모 사용자'}>{authEnabled?'?':'M'}</span>}</div></header><main id="main" tabIndex={-1}>{gated?(authReady?<LoginScreen/>:<div className="initial-loading" role="status"><div className="loading-orbit"/><strong>로그인 상태를 확인하고 있어요.</strong></div>):blocked?<div className="login-page"><section className="login-card" role="alert"><span className="eyebrow">ACCOUNT PAUSED</span><h1>계정이 일시 정지되었습니다<span className="accent-dot">.</span></h1><p>{SUSPENDED_MESSAGE}</p><button type="button" className="button secondary login-google" onClick={()=>void logout()}><LogOut size={15}/>로그아웃</button></section></div>:needProfile?(meReady?<ProfileForm mode="required"/>:<div className="initial-loading" role="status"><div className="loading-orbit"/><strong>회원 정보를 확인하고 있어요.</strong></div>):<div key={path} className="route-fade">{children}</div>}</main>{conversationsOn&&convOpen&&<div className="conv-overlay"><button type="button" className="conv-backdrop" aria-label="대화 목록 닫기" onClick={()=>setConvOpen(false)}/><aside className="conv-sheet" role="dialog" aria-label="대화 목록"><div className="conv-sheet-head"><strong>대화</strong><button type="button" onClick={()=>setConvOpen(false)}>닫기</button></div><ConversationList onPick={()=>setConvOpen(false)}/></aside></div>}<footer className="app-footer"><span>MARVIA <span className="muted">/</span> 근거가 보이는 화물 추적</span><span>{isLive?'':'가공 데이터 데모 · '}모든 시각은 한국 시간</span></footer></div></div>;
}
