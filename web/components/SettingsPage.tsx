'use client';
/** 설정·내 정보 화면. 시안(4-1~4-5, 3-5)이 다섯 화면으로 나눈 것을 /settings 안의 하위 탭으로 옮겼다.
 * 하위 이동은 제목 아래의 밑줄 탭 줄이 맡고, 고른 탭 밑의 막대가 미끄러지듯 따라간다.
 * 판단 기준은 읽기 전용 (SDD 5.13). 설정 키·파일 경로·모델 설정은 일반 사용자에게 내지 않는다.
 * 사이드바 계정 창은 ?tab=profile|rules|account 로 연다. 카카오에서 돌아오면(?kakao=) 연결 상태가 있는 "알림·판정 기준" 탭을 연다. KakaoPanel이 그 값을 읽고 주소에서 지우므로 여기서는 지우지 않는다.
 * 탭 종류는 TABS가 정하고, 각 탭 안의 화면은 기존 컴포넌트(ProfileForm·MemoryPanel·KakaoPanel·AccountPanel)를 그대로 쓴다 (동작·접근성 유지).
 */
import {useCallback, useEffect, useLayoutEffect, useRef, useState} from 'react';
import {Info, LockKeyhole} from 'lucide-react';
import {useApp} from './AppProvider';
import {ProfileForm} from './ProfileForm';
import {MemoryPanel} from './MemoryPanel';
import {KakaoPanel} from './KakaoPanel';
import {AccountPanel} from './AccountPanel';

type Tab = 'profile' | 'memory' | 'rules' | 'account';
// "조회 이력" 탭을 뺐다(사이드바 화물 > 조회 이력 /history가 같은 화면). "설정" 탭은 내용(기준·카카오 알림)이 잘 드러나게 "알림·판정 기준"으로 바꿨다. 탭 키 rules는 그대로.
// 탭 아래 설명 문장(lead)은 뺐다. 계정 탭 이름은 사이드바 계정 창과 맞춰 "계정 관리" (29번)
const TABS: {key: Tab; label: string}[] = [
  {key: 'profile', label: '회원 정보'},
  {key: 'memory', label: '기억한 화물'},
  {key: 'rules', label: '알림·판정 기준'},
  {key: 'account', label: '계정 관리'},
];

export function SettingsPage(){
  const [tab, setTab] = useState<Tab>('rules');
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [bar, setBar] = useState<{left: number; width: number} | null>(null);
  // 주소의 ?tab= 또는 카카오 복귀(?kakao=)를 처음 한 번만 읽는다. 서버 그림과 어긋나지 않게 마운트 뒤에 읽는다
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const want = p.get('tab');
    // 옛 링크 ?tab=history는 /history로 보낸다 (48번: 탭이 없어졌으므로)
    if (want === 'history') { window.location.replace('/history'); return; }
    if (p.get('kakao') !== null) setTab('rules');
    else if (TABS.some(t => t.key === want)) setTab(want as Tab);
    // 사이드바 계정 창이 이미 열린 설정 화면에서 다른 탭을 고르면 주소만 바뀌므로, 이벤트로 탭을 따라간다 (Shell openTab)
    const onTab = (e: Event) => { const k = (e as CustomEvent<string>).detail; if (TABS.some(t => t.key === k)) setTab(k as Tab); };
    window.addEventListener('marvia:settings-tab', onTab);
    return () => window.removeEventListener('marvia:settings-tab', onTab);
  }, []);
  // 고른 탭 밑의 막대 위치. 탭 줄이 가로로 밀리는 좁은 화면에서도 같은 줄 안에서 계산하므로 함께 움직인다
  const place = useCallback(() => {
    const el = tabRefs.current[TABS.findIndex(t => t.key === tab)];
    if (el) setBar({left: el.offsetLeft, width: el.offsetWidth});
  }, [tab]);
  useLayoutEffect(() => {
    place();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  }, [place]);
  useEffect(() => { void document.fonts?.ready.then(place); }, [place]);
  return <div className="page st-page">
    <header className="st-head"><h1>내 정보와 설정</h1></header>
    <nav className="st-tabs" aria-label="설정·내 정보 구역">{TABS.map((t, i) =>
      <button key={t.key} ref={el => { tabRefs.current[i] = el; }} type="button" className={`st-tab${t.key === tab ? ' on' : ''}`} aria-current={t.key === tab ? 'page' : undefined} onClick={() => setTab(t.key)}>{t.label}</button>)}
      {bar && <span className="st-tab-bar" aria-hidden="true" style={{transform: `translateX(${bar.left}px)`, width: bar.width}}/>}</nav>
    <div className="st-panel" key={tab}>
      {tab === 'profile' && <ProfileTab/>}
      {tab === 'memory' && <MemoryPanel/>}
      {tab === 'rules' && <RulesTab/>}
      {tab === 'account' && <AccountPanel/>}
    </div>
  </div>;
}

/** 회원 정보: 입력 폼 하나. 로그인 계정(이메일)은 제목 아래 작은 글로만 둔다 (오른쪽에 큰 글로 떠 있던 블록을 뺐다) */
function ProfileTab(){
  const {authEnabled, user} = useApp();
  const usable = authEnabled && !!user;
  if (!usable) return <p className="st-note">{authEnabled ? '로그인하면 회원 정보를 확인하고 고칠 수 있어요.' : '지금은 로그인 기능이 꺼져 있어 회원 정보를 받지 않아요.'}</p>;
  return <section className="st-card" aria-labelledby="st-profile-title"><h2 id="st-profile-title">내 회원 정보</h2><p className="st-email">{user.email ?? user.name ?? user.id}</p><ProfileForm mode="edit"/></section>;
}

/** 설정: 판단 기준(읽기 전용), 신호 우선순위, 카카오 알림, 운영자만 보는 모델 설정. 폭이 넓으면 칸이 늘어난다 */
function RulesTab(){
  const {data, isOperator} = useApp();
  const s = data.settings;
  return <div className="st-cols rules">
    <section className="st-card"><div className="st-card-head"><h2>이상 신호 기준</h2>
      <span className="st-icon-tip" role="img" aria-label="보기만 가능" title="보기만 가능해요"><LockKeyhole size={18}/></span>
      {isOperator && <span className="st-icon-tip" role="img" aria-label={`출처 ${s.source}, ${s.read_at} 확인`} title={`출처: ${s.source} (${s.read_at} 확인)`}><Info size={18}/></span>}</div>
      <dl className="st-rows">{s.thresholds.map(t => <div key={t.key} className="st-row"><dt>{t.label}</dt><dd>{t.value} {t.unit}</dd></div>)}</dl></section>
    <section className="st-card"><h2>서로 다른 신호, 무엇을 믿나요?</h2>
      <ol className="st-priority">{s.priority.map((p, i) => <li key={p}><span>0{i + 1}</span>{p}</li>)}</ol></section>
    <KakaoPanel/>
    {isOperator && <ModelCard rows={[['판정 모델', s.model], ['평가 모델', s.judge_model], ['프롬프트 버전', s.prompt_version], ['요청당 토큰 상한', s.token_limit], ['일일 비용 상한', s.daily_budget]]}/>}
  </div>;
}

/** 운영자용 모델·프롬프트 설정. isOperator일 때만 그려진다(위 RulesTab). 값이 있는 줄만 보이고, 하나도 없으면 한 줄로 알린다.
 * 전에는 다섯 줄이 모두 "확인되지 않음"으로 채워져 고장처럼 보였다 (UI 점검 V7). 값을 지어내지 않는다 */
function ModelCard({rows}:{rows:[string,unknown][]}){
  const known = rows.filter(([, v]) => v !== null && v !== undefined && v !== '');
  return <section className="st-card"><h2>모델과 프롬프트</h2>{known.length
    ? <dl className="st-rows">{known.map(([label, value]) => <div className="st-row" key={label}><dt>{label}</dt><dd>{String(value)}</dd></div>)}</dl>
    : <p className="st-note">운영 설정 정보가 없어요. 서버에서 설정 값을 받으면 여기에 나와요.</p>}</section>;
}
