'use client';
/** E10 소개 페이지 (로그인 안 한 사람용 랜딩). 수입자에게 "무엇을 해 주는지"를 그림으로 보여 주고 시작하기로 잇는다.
 * 디자인(10-06 3차): 흰 상자 대신 큰 글자·여백·그림으로 짠다. 제품 화면은 체험(데모) 화면을 2배율로 캡처한 이미지(public/about/*.webp).
 * 기술 구조(FastAPI 등)와 평가 표는 수입자에게 의미가 없어 뺐다. 평가는 운영자가 /metrics 에서 본다.
 * 문구는 실제 있는 기능만 말한다: 선박 식별, 신호 비교(AIS·해수부 입항 예정·통관), 판정, 근거. 스타일은 app/styles/entry.css (intro-*).
 */
import {useEffect, useRef} from 'react';
import Link from 'next/link';
import {ArrowRight, Check, ChevronLeft, ChevronRight, Eye, Layers3, OctagonAlert, Search, ShieldCheck, Info} from 'lucide-react';
import {isLive} from '@/lib/api';

/** 어떻게 판단하나요 3단계. 제품이 실제로 하는 일만 적는다 (식별 → 신호 비교 → 판정). */
const STEPS = [
  {icon: Search, title: '내 화물의 배가 맞는지 확인해요', text: '이름이 같아도 같은 배가 아닐 수 있어요. 확실하지 않으면 후보와 추가 정보를 물어봐요.'},
  {icon: Layers3, title: '믿을 신호를 골라요', text: '선박 위치 신호(AIS), 해수부 입항 예정, 통관 정보를 비교하고 출처와 시각을 함께 보여줘요.'},
  {icon: ShieldCheck, title: '내 일정에 맞춰 알려줘요', text: '판매 예정일을 기준으로 판단해요. 확실하지 않은 정보는 확실하지 않다고 솔직하게 말해요.'},
];

/** 판정 세 등급. 색은 순항·주의·긴급에만 쓴다. 할 일 문구는 이해를 돕는 예시다. */
const VERDICTS = [
  {icon: Check, title: '순항', cls: 'fine', text: '확인된 근거에 이상 신호가 없어요', todo: '지금은 따로 할 일이 없어요.'},
  {icon: Eye, title: '주의', cls: 'watch', text: '서로 다르거나 오래된 정보가 있어요', todo: '포워더에게 선박 운항 상황과 입항 예정일을 확인하세요.'},
  {icon: OctagonAlert, title: '긴급', cls: 'act', text: '판매 일정이나 화물 진행을 바로 확인해야 해요', todo: '판매 일정을 조정할지 바로 정하세요.'},
];

/** 화면 캡처 세 장. 체험 화면이라 안의 값은 예시다. */
const SHOTS = [
  {src: '/about/shot-result.webp', title: '조회 결과', text: '판정과 할 일, 지도, 통관 단계를 한 화면에서 봐요.', alt: 'Marvia 조회 결과 화면. 지도 위에 주의 등급과 여유 일수가 보이고, 아래에 출항지와 통관 진행이 이어져요.', w: 2416, h: 1673},
  {src: '/about/shot-watch.webp', title: '지켜보는 화물 지도', text: '지켜보는 화물이 어디쯤 오는지 지도 하나로 봐요.', alt: '지켜보는 화물 지도 화면. 부산항 쪽으로 오는 선박과 이동 경로가 지도에 있고, 오른쪽에 화물 목록과 판정 등급이 있어요.', w: 2416, h: 1673},
  {src: '/about/shot-cargo.webp', title: '화물 현황표', text: '신용장별 출항, 입항, 입고를 표로 한눈에 봐요.', alt: 'Marvia 화물 현황표 화면. 신용장과 B/L별로 출항, 입항, 입고 날짜와 포워더, 선사, 컨테이너가 한 줄씩 보여요.', w: 2416, h: 1213},
];

/** 스크롤해서 보이면 .in 을 붙인다. 모션 줄이기 설정이면 바로 보이게 한다 (CSS도 같이 막는다). */
function useReveal() {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = root.current; if (!el) return;
    const items = Array.from(el.querySelectorAll<HTMLElement>('.rv'));
    if (!('IntersectionObserver' in window) || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      items.forEach(i => i.classList.add('in')); el.classList.add('intro-ready'); return;
    }
    el.classList.add('intro-ready');  // 이 클래스가 붙은 뒤에만 숨겼다가 보여 준다 (자바스크립트가 꺼져도 글은 보인다)
    const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }), {threshold: .15, rootMargin: '0px 0px -8% 0px'});
    items.forEach(i => io.observe(i));
    return () => io.disconnect();
  }, []);
  return root;
}

export default function AboutPage() {
  const root = useReveal();
  const strip = useRef<HTMLUListElement>(null);
  const scrollShots = (dir: number) => strip.current?.scrollBy({left: dir * (strip.current.clientWidth * .8), behavior: 'smooth'});
  return <div className="page intro-page" ref={root}>
    <section className="intro-hero">
      <div className="intro-hero-copy">
        {/* 로고 이미지 안에 '수입 화물 비서'가 들어 있어 따로 쓰지 않는다 */}
        <img className="intro-logo rv" src="/brand/marvia-logo.svg" alt="Marvia" height={40}/>
        <h1 className="rv" style={{'--i': 1} as React.CSSProperties}>내 수입 화물,<br/>지금 신경 써야 할까?</h1>
        <p className="intro-sub rv" style={{'--i': 2} as React.CSSProperties}>B/L 하나로 내 화물이 제때 오는지 판정하고, 왜 그런지 근거까지 보여 드려요.</p>
        <div className="rv" style={{'--i': 3} as React.CSSProperties}>
          <Link href="/" className="button primary intro-cta">시작하기 <ArrowRight size={20}/></Link>
        </div>
      </div>
      <figure className="intro-hero-visual rv" style={{'--i': 2} as React.CSSProperties}>
        <img src="/about/hero-result.webp" width={1452} height={1250} alt="Marvia 조회 결과 화면. 지도에 선박 위치가 있고 주의 등급, 여유 4일, 출항지와 통관 단계가 보여요."/>
      </figure>
    </section>

    <section className="intro-section" aria-labelledby="intro-how">
      <h2 id="intro-how" className="rv">어떻게 판단하나요</h2>
      <ol className="intro-steps">
        {STEPS.map(({icon: Icon, title, text}, i) => <li className="rv" style={{'--i': i} as React.CSSProperties} key={title}>
          <span className="intro-step-icon"><Icon size={24} strokeWidth={1.9}/></span>
          <h3>{title}</h3>
          <p>{text}</p>
        </li>)}
      </ol>
    </section>

    <section className="intro-section" aria-labelledby="intro-verdict">
      <h2 id="intro-verdict" className="rv">짧은 판정, 분명한 다음 행동</h2>
      {/* 세 색 막대: 왼쪽에서 오른쪽으로 갈수록 급해진다. 글자로 같은 뜻을 아래에 적어 색만으로 전하지 않는다 */}
      <div className="intro-scale rv" role="img" aria-label="판정은 순항, 주의, 긴급 세 단계예요. 오른쪽으로 갈수록 급해요.">
        <span className="fine"/><span className="watch"/><span className="act"/>
      </div>
      <ul className="intro-verdicts">
        {VERDICTS.map(({icon: Icon, title, cls, text, todo}, i) => <li className="rv" style={{'--i': i} as React.CSSProperties} key={title}>
          <span className={`verdict-badge lg ${cls}`}><Icon size={18}/>{title}</span>
          <p className="intro-verdict-text">{text}</p>
          <p className="intro-todo"><span>할 일 예시</span>{todo}</p>
        </li>)}
      </ul>
      <p className="intro-note rv">근거가 모자라 판정할 수 없을 땐 판정 대신 추가 정보를 물어봐요.</p>
    </section>

    <section className="intro-section" aria-labelledby="intro-data">
      <h2 id="intro-data" className="rv">흩어진 정보를 한곳에서 모아요</h2>
      <p className="intro-lead rv">통관, 선박 위치, 입항 예정은 따로따로 확인해야 했어요. Marvia가 한꺼번에 모아 서로 맞는지 비교해요.</p>
      <div className="intro-diagram rv">
        <DataFlow/>
      </div>
    </section>

    <section className="intro-section" aria-labelledby="intro-shots">
      <div className="intro-shots-head rv">
        <h2 id="intro-shots">이런 화면으로 보여 드려요</h2>
        {/* 가로 띠를 밀어 넘기는 버튼. 마우스만 쓰는 사람도 세 장을 다 볼 수 있게 한다 */}
        <div className="intro-shots-nav">
          <button type="button" aria-label="이전 화면" title="이전 화면" onClick={() => scrollShots(-1)}><ChevronLeft size={20} strokeWidth={1.9}/></button>
          <button type="button" aria-label="다음 화면" title="다음 화면" onClick={() => scrollShots(1)}><ChevronRight size={20} strokeWidth={1.9}/></button>
        </div>
      </div>
      <ul className="intro-shots" ref={strip} tabIndex={0} aria-label="화면 예시 목록, 좌우 화살표 키로 넘겨 볼 수 있어요">
        {SHOTS.map((s, i) => <li className="rv" style={{'--i': i} as React.CSSProperties} key={s.src}>
          <img src={s.src} width={s.w} height={s.h} alt={s.alt} loading="lazy"/>
          <h3>{s.title}</h3>
          <p>{s.text}</p>
        </li>)}
      </ul>
    </section>

    <section className="intro-final rv">
      <h2>지금 내 화물부터 확인해 보세요</h2>
      <Link href="/" className="button primary intro-cta">시작하기 <ArrowRight size={20}/></Link>
      <p className="intro-scope"><Info size={16} aria-hidden="true"/>부산항으로 들어오는 해상 수입 화물, 통관 단계 설명까지 지원해요.{!isLive && ' 체험용 화면의 B/L, 선박, 위치, 시각은 모두 예시 값이에요.'}</p>
    </section>
  </div>;
}

/** 정보가 모이는 그림. 왼쪽 세 곳(통관, 선박 위치, 입항 예정) → Marvia → 판정. 넓은 화면은 가로, 좁은 화면은 세로 그림을 쓴다. */
function DataFlow() {
  const label = '관세청 UNI-PASS의 통관 정보, 선박 위치 신호, 해수부 입항 예정 세 가지를 Marvia가 모아 비교하고, 순항 주의 긴급 중 하나로 판정해요.';
  const sources = [
    {t: '통관 정보', s: '관세청 UNI-PASS'},
    {t: '선박 위치', s: '위치 신호(AIS)'},
    {t: '입항 예정', s: '해양수산부'},
  ];
  return <>
    <svg className="flow flow-wide" viewBox="0 0 880 330" role="img" aria-label={label}>
      {sources.map((x, i) => <g key={x.t}>
        <rect className="f-src" x="0" y={20 + i * 100} width="230" height="80" rx="12"/>
        <text className="f-t" x="24" y={53 + i * 100}>{x.t}</text>
        <text className="f-s" x="24" y={79 + i * 100}>{x.s}</text>
        <path className="f-line" d={`M230 ${60 + i * 100} C 300 ${60 + i * 100}, 300 165, 360 165`} pathLength="1"/>
      </g>)}
      <rect className="f-core" x="360" y="105" width="180" height="120" rx="16"/>
      <text className="f-core-t" x="450" y="157" textAnchor="middle">Marvia</text>
      <text className="f-core-s" x="450" y="184" textAnchor="middle">비교하고 근거 찾기</text>
      <path className="f-line" d="M540 165 L 650 165" pathLength="1"/>
      <path className="f-arrow" d="M644 157 L 654 165 L 644 173"/>
      {(['fine', 'watch', 'act'] as const).map((c, i) => <g key={c}>
        <rect className={`f-v ${c}`} x="670" y={42 + i * 90} width="210" height="62" rx="12"/>
        <text className={`f-vt ${c}`} x="775" y={80 + i * 90} textAnchor="middle">{['순항', '주의', '긴급'][i]}</text>
      </g>)}
    </svg>
    <svg className="flow flow-tall" viewBox="0 0 340 560" role="img" aria-label={label}>
      {sources.map((x, i) => <g key={x.t}>
        <rect className="f-src" x={i * 116} y="0" width="108" height="86" rx="12"/>
        <text className="f-t" x={i * 116 + 54} y="38" textAnchor="middle">{x.t}</text>
        <text className="f-s" x={i * 116 + 54} y="62" textAnchor="middle">{['UNI-PASS', 'AIS', '해수부'][i]}</text>
        <path className="f-line" d={`M${i * 116 + 54} 86 C ${i * 116 + 54} 150, 170 150, 170 200`} pathLength="1"/>
      </g>)}
      <rect className="f-core" x="70" y="200" width="200" height="110" rx="16"/>
      <text className="f-core-t" x="170" y="250" textAnchor="middle">Marvia</text>
      <text className="f-core-s" x="170" y="278" textAnchor="middle">비교하고 근거 찾기</text>
      <path className="f-line" d="M170 310 L 170 380" pathLength="1"/>
      <path className="f-arrow" d="M162 374 L 170 384 L 178 374"/>
      {(['fine', 'watch', 'act'] as const).map((c, i) => <g key={c}>
        <rect className={`f-v ${c}`} x={i * 116} y="400" width="108" height="64" rx="12"/>
        <text className={`f-vt ${c}`} x={i * 116 + 54} y="440" textAnchor="middle">{['순항', '주의', '긴급'][i]}</text>
      </g>)}
    </svg>
  </>;
}
