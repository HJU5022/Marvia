/** Judgement is conditional on verdict, not on status. No client-side assessment. E4.
 * days_margin = 판매 예정일 - 신뢰 입항 예정일 (서버 계산, SDD 5.8). 음수는 "입항이 판매일보다 늦다"는 뜻이지
 * "판매일이 이미 지났다"는 뜻이 아니다 (구현작업서 8절, 설명 오류 발견). 그래서 "초과" 대신 "늦음"으로 쓰고 한 줄 풀어 준다. */
import {Info} from 'lucide-react';
import type {ReactNode} from 'react';
import type {AgentResponse,AgentRequest} from '@/lib/types';
import {day,fieldLabel,sourceLabels} from '@/lib/format';

/** 어려운 용어·판단에 영향 주는 주의에 다는 작은 설명. 글자 없이 ⓘ만 보이고(badge를 주면 그 글자가 작은 배지로 보인다), 누르면 설명이 펼쳐진다.
 * 문장을 화면에 늘어놓지 않으려는 01_공통 "작은 글씨 규칙"을 한 곳에서 지키려고 여기 둔다. 통관·일정·지켜보기 칸이 같이 쓴다. */
export function InfoTip({label,badge,children}:{label:string;badge?:string;children:ReactNode}) {
 return <details className={badge?'info-tip as-badge':'info-tip'}><summary aria-label={label}>{badge??<Info size={15} aria-hidden="true"/>}</summary><span className="info-pop" role="note">{children}</span></details>;
}
/** 출처끼리 어긋난 신호는 문장 대신 작은 배지로 보인다. 도착 예정끼리면 "예정일 2곳 다름" */
export function conflictBadge(signals:string[]) {
 return signals.length>1&&signals.every(f=>f.endsWith('_eta'))?`예정일 ${signals.length}곳이 서로 달라요`:`${signals.map(fieldLabel).join(' ↔ ')} 다름`;
}
export function VerdictCard({response:r,request}:{response:AgentResponse;request:AgentRequest}) {
 if(!r.verdict)return null;
 const m=r.days_margin;
 // 여유 일수: 색은 판정 등급을 따른다. 값이 없으면 회색 안내 (판매일을 안 적었으면 "판매일 입력 필요")
 const slack=m===null
  ?<span className="slack-empty">{request.sale_due_date?'미확인':'판매 예정일 입력 필요'}</span>
  :<strong className="slack-value">{m<0?`${Math.abs(m)}일 늦음`:`여유 ${m}일`}</strong>;
 // 등급 배지는 지도 위 카드(MapPanel)와 대화 답 말풍선에 크게 있다. 이 칸은 지금 할 일과 여유 일수가 주인공이다 (마누스 시안 2-2)
 return <section className={`verdict-hero ${r.verdict}`} aria-label="화물 판정">
  <div className="verdict-body">
   <div className="verdict-todo"><span className="verdict-label">지금 할 일</span>{r.actions.length?r.actions.map((a,i)=><p key={i}>{a}</p>):<p>지금 안내할 할 일이 없어요.</p>}</div>
   <div className={`verdict-slack ${m===null?'empty':r.verdict}`} aria-label="판매 예정일까지">{slack}{request.sale_due_date&&<small>판매 예정일 {day(request.sale_due_date)}</small>}</div>
  </div>
  {/* 음수는 "입항이 판매일보다 늦다"는 뜻이다. 판매일이 지났다는 뜻으로 읽히지 않게 이 한 줄은 남긴다 */}
  {m!==null&&m<0&&<p className="margin-note">믿을 만한 입항 예정일이 판매 예정일보다 늦어요. 판매 예정일이 이미 지났다는 뜻은 아니에요.</p>}
 </section>;
}
