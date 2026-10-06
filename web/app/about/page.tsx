'use client';
/** E10 소개 페이지 (로그인 안 한 사람용 홍보 1장 → 시작하기). 제품 정의와 지원 범위.
 * 기술 구조와 평가 표는 운영자에게만 보인다 (10-02 화면 용어 점검, 평가 지표는 10-01부터 운영자 전용).
 * 디자인(10-06): 큰 한 줄 + 파란 버튼 하나, 아래로 쉬운 카드. 영어 눈썹글·그라데이션 없음. 스타일은 app/styles/entry.css (intro-*).
 * 문구는 실제 있는 기능만 말한다: 선박 식별, 신호 비교(AIS·해수부 입항 예정·통관), 판정, 근거.
 */
import Link from 'next/link';
import {ArrowRight, Check, Eye, HelpCircle, Layers3, OctagonAlert, Search, ShieldCheck} from 'lucide-react';
import {useApp} from '@/components/AppProvider';
import {isLive} from '@/lib/api';

/** 소개 카드 세 장. 제품이 실제로 하는 일만 적는다 (식별 → 신호 비교 → 판정). */
const STEPS = [
  {icon: Search, title: '내 화물의 배가 맞는지', text: '이름이 같아도 같은 배는 아닙니다. 확정할 수 없으면 후보와 추가 정보를 묻습니다.'},
  {icon: Layers3, title: '어떤 신호를 믿어야 할지', text: '선박 위치 신호(AIS), 해수부 입항 예정, 통관 정보를 비교하고 출처와 시각을 함께 보여줍니다.'},
  {icon: ShieldCheck, title: '내 일정에 무엇이 필요한지', text: '판매 예정일을 기준으로 판단합니다. 확실하지 않은 정보는 확실하지 않다고 말합니다.'},
];

/** 판정 안내. 색은 판정 등급(순항·주의·긴급)에만 쓰고 '정보 확인 필요'는 회색이다. */
const VERDICTS = [
  {icon: Check, title: '순항', text: '확인된 근거에 이상 신호가 없음', cls: 'fine'},
  {icon: Eye, title: '주의', text: '상충하거나 오래된 정보를 재확인', cls: 'watch'},
  {icon: OctagonAlert, title: '긴급', text: '판매 일정 또는 화물 진행 확인 필요', cls: 'act'},
  {icon: HelpCircle, title: '정보 확인 필요', text: '판정 대신 추가 정보를 요청', cls: 'neutral'},
];

export default function AboutPage() {
  const {data, isOperator} = useApp();
  return <div className="page intro-page">
    <section className="intro-hero">
      <img className="intro-logo" src="/brand/marvia-logo.svg" alt="Marvia" height={32}/>
      <p className="intro-tagline">수입 화물 비서</p>
      <h1>내 수입 화물,<br/>지금 신경 써야 할까?</h1>
      <p className="intro-sub">B/L 하나로 내 화물이 제때 오는지 판정하고, 왜 그런지 근거까지 보여줍니다.</p>
      <Link href="/" className="button primary intro-cta">시작하기 <ArrowRight size={20}/></Link>
    </section>

    <section className="intro-section" aria-labelledby="intro-why">
      <h2 id="intro-why">“배가 어디 있지?”에서<br/>“지금 뭘 해야 하지?”까지</h2>
      <p>소량 해상 수입자는 여러 사이트의 위치와 입항 예정을 직접 비교해야 합니다. Marvia는 내 화물의 배가 맞는지 먼저 확인하고, 서로 다른 신호를 정리해 판매 일정에 필요한 다음 행동을 알려줍니다.</p>
      <div className="intro-cards">
        {STEPS.map(({icon: Icon, title, text}) => <div className="intro-card" key={title}>
          <span className="intro-card-icon"><Icon size={22}/></span>
          <h3>{title}</h3>
          <p>{text}</p>
        </div>)}
      </div>
    </section>

    <section className="intro-section" aria-labelledby="intro-verdict">
      <h2 id="intro-verdict">짧은 판정,<br/>분명한 다음 행동</h2>
      <div className="intro-verdicts">
        {VERDICTS.map(({icon: Icon, title, text, cls}) => <div key={title}>
          <span className={`verdict-badge ${cls}`}><Icon size={16}/>{title}</span>
          <p>{text}</p>
        </div>)}
      </div>
    </section>

    {isOperator && <section className="intro-section" aria-labelledby="intro-arch">
      <h2 id="intro-arch">판정 뒤의 흐름</h2>
      <p>운영자용 구조 설명입니다.</p>
      <div className="intro-flow" role="img" aria-label="사용자 입력을 Next.js가 받아 FastAPI로 전달. FastAPI가 UNI-PASS와 MCP 도구 및 규칙·LLM 판정을 통해 근거 있는 결과를 반환하고 Langfuse와 평가셋으로 검증합니다.">
        <div><strong>B/L · 판매 예정일</strong><span>Next.js 화면</span></div>
        <ArrowRight className="intro-flow-arrow" size={20}/>
        <div><strong>FastAPI</strong><span>식별 → 신호 → 판정</span></div>
        <ArrowRight className="intro-flow-arrow" size={20}/>
        <div><strong>규칙 + LLM</strong><span>UNI-PASS · MCP 도구</span></div>
      </div>
      <p className="intro-flow-foot">Langfuse 관측 · 출력 계약 검증 · 평가셋 비교</p>
    </section>}

    {isOperator && <section className="intro-section" aria-labelledby="intro-eval">
      <h2 id="intro-eval">확인할 수 있는 결과</h2>
      <table className="intro-table"><caption className="sr-only">평가 항목과 측정 상태</caption>
        <thead><tr><th>평가 항목</th><th>결과</th></tr></thead>
        <tbody>{data.metrics.kpis.map(k => <tr key={k.id}><td>{k.label}</td><td>{k.value ?? '미측정'}</td></tr>)}</tbody>
      </table>
      <Link href="/metrics" className="intro-link">평가 지표 자세히 <ArrowRight size={16}/></Link>
    </section>}

    <section className="intro-scope">
      <strong>현재 지원 범위</strong>
      <p>부산항으로 들어오는 해상 수입 화물 · 통관 단계 해설까지{!isLive && <><br/>이 체험용 예시의 B/L·선박·위치·시각은 모두 가공값이며 실제 화물 추적 결과가 아닙니다.</>}</p>
    </section>
  </div>;
}
