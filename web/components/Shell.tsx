'use client';
/** 고정 사이드바와 상단 바. 로그인이 켜져 있으면 로그인 전에는 본문 대신 LoginScreen을 보여 준다 (G3, 소개 페이지는 예외). */
import Link from 'next/link';
import {usePathname} from 'next/navigation';
import {useState} from 'react';
import {ArrowUpRight, Boxes, ChartNoAxesCombined, Compass, History, LogOut, Settings2, Waves} from 'lucide-react';
import {LoginScreen} from './LoginScreen';
import {signOut} from '@/lib/auth';
import {useApp} from './AppProvider';
import {isLive} from '@/lib/api';
const links=[{href:'/',label:'내 화물',en:'MY CARGO',icon:Boxes},{href:'/history',label:'조회 이력',en:'HISTORY',icon:History},{href:'/metrics',label:'평가 지표',en:'EVALUATION',icon:ChartNoAxesCombined},{href:'/settings',label:'설정',en:'SETTINGS',icon:Settings2}];
export function Shell({children}:{children:React.ReactNode}) {
 const path=usePathname();const {data,authEnabled,authReady,user,reset}=useApp();const [menu,setMenu]=useState(false);
 // 로그인 확인 전(authReady=false)에는 빈 본문. 로그인 화면이 잠깐 깜빡이지 않게 한다
 const gated=authEnabled&&path!=='/about'&&(!authReady||!user);
 const initial=(user?.name??user?.email??'M').trim().charAt(0).toUpperCase();
 async function logout(){setMenu(false);await signOut();reset();}
 return <div className="app-shell"><a className="skip-link" href="#main">본문으로 건너뛰기</a><aside className="sidebar"><Link href="/" className="brand" aria-label="Marvia 내 화물"><span className="brand-symbol"><Waves size={25}/></span><span>marvia<span className="brand-dot">.</span></span></Link><div className="sidebar-kicker">YOUR CARGO, IN CLEAR VIEW</div><nav aria-label="주 메뉴">{links.map(({href,label,en,icon:Icon})=><Link key={href} href={href} className={`nav-link ${path===href?'active':''}`} aria-current={path===href?'page':undefined}><Icon size={19}/><span>{label}<small>{en}</small></span>{path===href&&<span className="nav-dot"/>}</Link>)}</nav><div className="sidebar-bottom"><div className="port-stamp"><Compass size={28} strokeWidth={1.2}/><div>도착지를 넘어,<br/>판단의 근거까지.</div></div><Link className={`about-link ${path==='/about'?'active':''}`} href="/about">Marvia 소개 <ArrowUpRight size={16}/></Link><div className="sidebar-meta"><span className="online-dot"/> {isLive?'LIVE API':'LOCAL REPLAY'}<br/><span className="session-id">{isLive?(user?.email??(authEnabled?'로그인 전':'로그인 꺼짐 · 세션 구분')):data.demo.session_id}</span></div></div></aside><div className="workspace"><header className="workspace-bar"><span><span className="breadcrumb">워크스페이스</span><span className="slash">/</span>{links.find(l=>l.href===path)?.label??'Marvia 소개'}</span><div className="workspace-meta"><span className="port-label">{data.demo.port.code} · {data.demo.port.name}</span><span className="replay-chip"><span/>{isLive?'실시간 조회':'재생 · 가공 데이터'}</span>{user?<div className="user-menu"><button type="button" className="avatar" aria-label={`${user.email??'사용자'} 계정 메뉴`} aria-expanded={menu} onClick={()=>setMenu(m=>!m)}>{initial}</button>{menu&&<div className="user-popover" role="menu"><span className="user-name">{user.name??'로그인 사용자'}</span><span className="user-email">{user.email}</span><Link href="/settings" role="menuitem" onClick={()=>setMenu(false)}>계정과 기록 관리</Link><button type="button" role="menuitem" onClick={()=>void logout()}><LogOut size={14}/>로그아웃</button></div>}</div>:<span className="avatar" aria-label={authEnabled?'로그인 전':'데모 사용자'}>{authEnabled?'?':'M'}</span>}</div></header><main id="main" tabIndex={-1}>{gated?(authReady?<LoginScreen/>:<div className="initial-loading" role="status"><div className="loading-orbit"/><strong>로그인 상태를 확인하고 있어요.</strong></div>):children}</main><footer className="app-footer"><span>MARVIA <span className="muted">/</span> 근거가 보이는 화물 추적</span><span>{isLive?'':'가공 데이터 데모 · '}모든 시각 KST</span></footer></div></div>;
}
