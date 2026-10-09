'use client';
/** 사이드바의 "대화" 목록. ChatGPT·Claude처럼 날짜별 묶음, 지금 보는 대화는 강조한다.
 * "새 대화" 버튼은 사이드바 맨 위로 옮겼다. 이 목록은 withNew일 때만(좁은 화면 패널) 맨 위에 그린다.
 * 목록·열기·삭제 상태는 모두 AppProvider에 있고 여기서는 그리기와 "정말 지울까요?" 확인 한 단계만 가진다.
 * 로그인했을 때만 Shell이 그린다. 넓은 화면은 사이드바 안에, 좁은 화면(900px 이하)은 상단바의 "대화" 버튼이 여는 패널 안에 같은 컴포넌트를 쓴다.
 */
import {useState} from 'react';
import {usePathname, useRouter} from 'next/navigation';
import {Plus, Trash2} from 'lucide-react';
import {useApp} from './AppProvider';
import type {ConversationSummary} from '@/lib/types';

const GROUPS = ['오늘', '어제', '지난 7일', '지난 30일', '그 이전'] as const;

/** 수정 시각을 사용자의 로컬 날짜 기준 묶음으로. 날짜 경계는 자정이다 */
function groupOf(iso: string, now: Date): typeof GROUPS[number] {
  const t = new Date(iso); if (Number.isNaN(t.getTime())) return '그 이전';
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(t)) / 86_400_000);
  return days <= 0 ? '오늘' : days === 1 ? '어제' : days <= 7 ? '지난 7일' : days <= 30 ? '지난 30일' : '그 이전';
}

export function ConversationList({onPick, withNew = false}: {onPick?: () => void; withNew?: boolean}) {
  const {conversations, activeId, loading, opening, newConversation, openConversation, removeConversation} = useApp();
  const router = useRouter(), path = usePathname();
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const locked = loading || opening;  // 답을 기다리거나 불러오는 중에는 대화를 바꾸지 않는다

  const now = new Date();
  const grouped = GROUPS.map(g => ({g, items: conversations.filter(c => groupOf(c.updated_at, now) === g)})).filter(x => x.items.length > 0);

  function start() { setConfirmId(null); setError(''); newConversation(); onPick?.(); }
  async function open(c: ConversationSummary) {
    setConfirmId(null); setError('');
    // 이미 보던 대화여도 다른 화면(소개 등)에 있으면 채팅 화면으로 돌아간다. 예전에는 여기서 그냥 끝나 눌러도 아무 일이 없었다
    if (c.id === activeId) { onPick?.(); if (path !== '/') router.push(`/?c=${encodeURIComponent(c.id)}`); return; }
    onPick?.();
    await openConversation(c.id);
  }
  async function remove(id: string) {
    setBusyId(id); setError('');
    try { await removeConversation(id); setConfirmId(null); }
    catch (e) { setError(e instanceof Error ? e.message : '대화를 지우지 못했어요. 잠시 뒤 다시 시도해 주세요.'); }
    finally { setBusyId(null); }
  }

  // 클래스는 sb-cl-* (styles/sidebar.css). 사이드바와 좁은 화면 패널이 같은 모양을 쓴다
  return <div className="sb-cl">
    {withNew && <button type="button" className="sb-cl-new" onClick={start} disabled={locked}><Plus size={15} aria-hidden="true"/><span>새 대화</span></button>}
    {error && <p role="alert" className="sb-cl-error">{error}</p>}
    {grouped.length === 0 ? <p className="sb-cl-empty">저장된 대화가 없어요</p>
      : grouped.map(({g, items}) => <section key={g} className="sb-cl-group" aria-label={g}>
        <h3>{g}</h3>
        <ul>{items.map(c => {
          const active = c.id === activeId;
          return <li key={c.id} className={`sb-cl-row${active ? ' active' : ''}`}>
            {confirmId === c.id
              ? <div className="sb-cl-confirm" role="group" aria-label="대화 지우기 확인">
                  <span>이 대화를 지울까요?</span>
                  <button type="button" onClick={() => setConfirmId(null)} disabled={busyId === c.id}>취소</button>
                  <button type="button" className="danger" onClick={() => void remove(c.id)} disabled={busyId === c.id}>{busyId === c.id ? '지우는 중' : '지우기'}</button>
                </div>
              : <>
                  <button type="button" className="sb-cl-title" onClick={() => void open(c)} disabled={locked && !active} aria-current={active ? 'true' : undefined} title={c.title}>{c.title || '제목 없는 대화'}</button>
                  <button type="button" className="sb-cl-del" onClick={() => { setError(''); setConfirmId(c.id); }} disabled={locked} aria-label={`${c.title || '제목 없는 대화'} 지우기`}><Trash2 size={14}/></button>
                </>}
          </li>;
        })}</ul>
      </section>)}
  </div>;
}
