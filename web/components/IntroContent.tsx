'use client';
/** Marvia 소개 본문. 로그인 전 첫 화면(LoginScreen)과 사이드바의 /about 이 같은 본문을 쓴다. 디자인이 하나여야 해서 여기서만 짠다.
 * 아임웹 GLOBAL LOGISTICS 템플릿의 짜임을 따르되, 필요한 것만 가져왔다.
 *   가져온 것: 사진 꽉 찬 첫 화면 + 굵은 큰 제목, 숫자 줄, 글·그림 두 칸 단락, 연회색 바탕 기능 카드(엇갈림), 짙은 바탕 단락, 마지막 권유 상자, 강조색 하나
 *   버린 것: 공지 띠, 고객 후기·별점, 파트너 로고(우리에게 없는 것), 지어낸 숫자. 스크롤해야 나타나는 숨김 효과도 없앴다 (빠르게 내리면 빈 화면으로 보였다)
 * 숫자 줄은 우리가 실제로 잰 값만 싣는다: evals/results/b_20261007_0935.json (평가셋 30건, 서비스 모델 gemini-3.5-flash-lite, EVAL_REPORT.md 5절).
 * 다시 재면 EVAL 상수만 고친다. 실행하지 않은 숫자는 싣지 않는다 (CLAUDE.md).
 * 사진은 Unsplash 무료 사진 (web/public/landing/README.md). 스타일은 app/styles/landing.css (lp-*).
 */
import type {ReactNode} from 'react';
import {Anchor, BellRing, FileSearch, Info, ShieldCheck, Ship, Stamp} from 'lucide-react';

/** 사진을 화면 너비에 맞는 크기로 (가장 먼저 그려지는 첫 화면 사진이 무거웠다) */
const HERO_SRCSET = '/landing/port-800.webp 800w, /landing/port-1280.webp 1280w, /landing/port-1440.webp 1440w, /landing/port-1920.webp 1920w';
const SEA_SRCSET = '/landing/sea-800.webp 800w, /landing/sea-1280.webp 1280w, /landing/sea-1920.webp 1920w';
import {isLive} from '@/lib/api';

/** 평가셋 30건 실측 (b_20261007_0935.json). 숫자 줄과 출처 문장이 이 값 하나를 쓴다 */
const EVAL = {
  date: '10월 7일',
  total: 30,
  exact: 30,          // 정답과 판정·되묻기·보류가 모두 같은 건수 (exact_match)
  actMissed: 0,       // 지금 조치해야 할 화물을 놓친 건수 (act_recall 1.0)
  wrongVessel: 0,     // 다른 배를 내 배로 확정한 건수 (vessel_wrong_confirm 0건)
  customsGraded: 20,  // 통관 해설을 채점한 건수 (customs_graded)
  customsPass: 20,    // 그중 맞게 풀어 쓴 건수 (customs_explanation 1.0). 지연은 Vertex 직접 호출로 재서 서비스 경로 값이 아니라 싣지 않는다
};

/** 어떻게 판단하나요 4단계. 제품이 실제로 하는 일만 적는다 */
const STEPS = [
  {title: 'B/L 입력', text: 'B/L 번호 하나와 물건을 받아야 하는 날을 넣어요.'},
  {title: '내 배 확인', text: '이름이 같은 배가 여럿이면 함부로 고르지 않고 후보를 보여 드리고 물어봐요.'},
  {title: '신호 비교', text: '선박 위치(AIS), 해수부 입항 신고, 관세청 통관 단계를 서로 맞춰 봐요.'},
  {title: '판정과 근거', text: '판매 예정일에 맞춰 판정하고, 무엇을 믿었는지 출처와 시각을 함께 보여 드려요.'},
];

/** 기능 카드 4개. 실제로 있는 기능만 (판정, 되묻기, 통관 해설, 지켜보기·알림) */
const FEATURES = [
  {icon: ShieldCheck, title: '판정 3단계', text: '순항, 주의, 긴급 중 하나로 짧게 답하고 지금 할 일을 알려 드려요.'},
  {icon: Ship, title: '내 배인지 확인', text: '같은 이름의 배가 여럿이면 항차나 입항 예정일을 물어 확실히 가려요.'},
  {icon: Stamp, title: '통관 단계 해설', text: '세관 단계 이름과 그 뜻을 풀어 드리고, 관세사가 필요한 때를 알려 드려요.'},
  {icon: BellRing, title: '지켜보기와 알림', text: '화물을 지켜보다가 판정이 바뀌면 다음 접속이나 카카오톡으로 알려 드려요.'},
];

/** 판정 세 등급. 할 일은 이해를 돕는 예시다 */
const VERDICTS = [
  {cls: 'fine', name: '순항', mean: '확인된 근거에 이상 신호가 없어요.', todo: '지금은 따로 할 일이 없어요.'},
  {cls: 'watch', name: '주의', mean: '정보가 서로 다르거나 오래됐어요.', todo: '포워더에게 운항 상황과 입항 예정일을 확인하세요.'},
  {cls: 'act', name: '긴급', mean: '판매 일정이나 통관을 바로 확인해야 해요.', todo: '판매 일정을 조정할지 바로 정하세요.'},
];

/** 데이터 출처 세 곳 */
const SOURCES = [
  {icon: FileSearch, name: '관세청 UNI-PASS', what: '통관 진행 단계'},
  {icon: Anchor, name: '해양수산부', what: '입항 신고와 실제 입항'},
  {icon: Ship, name: '선박 위치 신호(AIS)', what: '위치, 속력, 목적지'},
];

/** navRight: 윗줄 오른쪽 자리 (로그인 전 화면은 로그인 버튼, 소개 페이지는 비움). action: 큰 시작 버튼 (소개 페이지는 링크, 로그인 전 화면은 구글 로그인). */
export function IntroContent({action, navRight, footer}: {action: ReactNode; navRight?: ReactNode; footer?: ReactNode}) {
  return <div className="lp">
    <header className="lp-nav">
      <div className="lp-nav-in">
        <a className="lp-logo" href="#top">Marvia</a>
        <nav className="lp-menu" aria-label="소개 메뉴">
          <a href="#how">어떻게 판단하나요</a><a href="#features">기능</a><a href="#verdict">판정</a><a href="#screens">화면</a>
        </nav>
        <div className="lp-nav-right">{navRight}</div>
      </div>
    </header>

    {/* 첫 화면: 항만으로 들어오는 배 사진에 굵은 제목. 배가 오른쪽에 있어 왼쪽 글과 겹치지 않고, 글자가 읽히게 왼쪽을 어둡게 덮는다 */}
    <section className="lp-hero" id="top">
      <img className="lp-hero-img" src="/landing/port-1440.webp" srcSet={HERO_SRCSET} sizes="100vw" alt="" width={1440} height={961} fetchPriority="high"/>
      <div className="lp-hero-shade" aria-hidden="true"/>
      <div className="lp-hero-in">
        <p className="lp-eyebrow light">수입 화물 비서</p>
        <h1>내 수입 화물,<br/>지금 신경 써야 할까?</h1>
        <p className="lp-hero-sub">B/L 하나로 내 화물이 판매 예정일 전에 오는지 판정하고, 왜 그런지 근거까지 보여 드려요.</p>
        <div className="lp-hero-actions">{action}<a className="lp-link light" href="#how">어떻게 판단하나요</a></div>
      </div>
    </section>

    {/* 숫자 줄: 실제로 잰 평가 결과만 */}
    <section className="lp-wrap lp-stats-sec" aria-labelledby="lp-stats">
      <h2 id="lp-stats" className="lp-center-title">근거로만 판정해요</h2>
      <p className="lp-center-sub">사람이 정답을 적어 둔 평가 화물 {EVAL.total}건으로 직접 재 본 결과예요 ({EVAL.date}).</p>
      <dl className="lp-stats">
        <div><dt>판정 일치</dt><dd>{EVAL.exact}<small>/{EVAL.total}</small></dd></div>
        <div><dt>긴급 화물 놓침</dt><dd>{EVAL.actMissed}<small>건</small></dd></div>
        <div><dt>다른 배를 내 배로 확정</dt><dd>{EVAL.wrongVessel}<small>건</small></dd></div>
        <div><dt>통관 단계 해설</dt><dd>{EVAL.customsPass}<small>/{EVAL.customsGraded}</small></dd></div>
      </dl>
    </section>

    {/* 어떻게 판단하나요: 왼쪽 단계, 오른쪽 실제 결과 화면 */}
    <section className="lp-wrap lp-split" id="how" aria-labelledby="lp-how">
      <div className="lp-split-text">
        <p className="lp-eyebrow">어떻게 판단하나요</p>
        <h2 id="lp-how">흩어진 정보를 맞춰 보고<br/>하나로 답해요</h2>
        <ol className="lp-steps">
          {STEPS.map(({title, text}, i) => <li key={title}>
            <span className="lp-step-no">{String(i + 1).padStart(2, '0')}</span>
            <div><h3>{title}</h3><p>{text}</p></div>
          </li>)}
        </ol>
      </div>
      <figure className="lp-split-media">
        <img src="/about/hero-result.webp" width={1424} height={1150} loading="lazy" alt="Marvia 조회 결과 화면. 지도에 선박 위치가 있고 주의 등급, 여유 4일, 출항지와 통관 단계가 보여요."/>
        <figcaption>실제 조회 결과 화면 (예시 화물)</figcaption>
      </figure>
    </section>

    {/* 데이터 출처: 넓은 사진 띠 위에 세 곳 */}
    <section className="lp-band" aria-labelledby="lp-src">
      <img className="lp-band-img" src="/landing/sea-1280.webp" srcSet={SEA_SRCSET} sizes="100vw" alt="" width={1280} height={851} loading="lazy"/>
      <div className="lp-band-shade" aria-hidden="true"/>
      <div className="lp-wrap lp-band-in">
        <p className="lp-eyebrow light">데이터 출처</p>
        <h2 id="lp-src">공공 데이터와 선박 위치 신호를 한 화면에</h2>
        <ul className="lp-sources">
          {SOURCES.map(({icon: Icon, name, what}) => <li key={name}><Icon size={22} strokeWidth={1.75} aria-hidden="true"/><b>{name}</b><span>{what}</span></li>)}
        </ul>
      </div>
    </section>

    {/* 기능: 연회색 바탕, 왼쪽 글 + 오른쪽 엇갈린 카드 4개 */}
    <section className="lp-soft" id="features" aria-labelledby="lp-feat">
      <div className="lp-wrap lp-feat">
        <div className="lp-feat-text">
          <p className="lp-eyebrow">기능</p>
          <h2 id="lp-feat">수입 담당자가<br/>매일 하던 확인을 대신해요</h2>
          <p className="lp-body">포워더에게 전화하고, 관세청과 해수부 사이트를 오가며 맞춰 보던 일을 한 번의 조회로 줄여요.</p>
          <img className="lp-feat-photo" src="/landing/terminal.jpg" width={1200} height={799} loading="lazy" alt=""/>
        </div>
        <ul className="lp-cards">
          {FEATURES.map(({icon: Icon, title, text}) => <li key={title}>
            <span className="lp-card-icon"><Icon size={22} strokeWidth={1.75} aria-hidden="true"/></span>
            <h3>{title}</h3><p>{text}</p>
          </li>)}
        </ul>
      </div>
    </section>

    {/* 판정: 짙은 바탕에 세 등급 카드 */}
    <section className="lp-dark" id="verdict" aria-labelledby="lp-verdict">
      <div className="lp-wrap">
        <p className="lp-eyebrow light center">판정</p>
        <h2 id="lp-verdict" className="lp-center-title light">짧은 판정, 분명한 다음 행동</h2>
        <ul className="lp-verdicts">
          {VERDICTS.map(v => <li key={v.name} className={v.cls}>
            <p className="lp-verdict-name"><span className={`lp-dot ${v.cls}`} aria-hidden="true"/>{v.name}</p>
            <p className="lp-verdict-mean">{v.mean}</p>
            <p className="lp-verdict-todo"><b>할 일 예시</b>{v.todo}</p>
          </li>)}
        </ul>
        <p className="lp-dark-note">근거가 모자라 판정할 수 없을 땐 판정 대신 추가 정보를 물어봐요.</p>
      </div>
    </section>

    {/* 화면 미리보기 */}
    <section className="lp-wrap lp-screens" id="screens" aria-labelledby="lp-screens">
      <p className="lp-eyebrow center">화면</p>
      <h2 id="lp-screens" className="lp-center-title">이런 화면으로 보여 드려요</h2>
      <ul className="lp-shots">
        <li>
          <a href="/about/shot-watch.webp" target="_blank" rel="noreferrer" aria-label="지켜보는 화물 지도 화면 크게 보기">
            <img src="/about/shot-watch.webp" width={2224} height={1456} loading="lazy" alt="지켜보는 화물 지도 화면. 부산항 쪽으로 오는 선박과 이동 경로가 지도에 있고, 오른쪽에 화물 목록과 판정 등급이 있어요."/>
          </a>
          <h3>지켜보는 화물 지도</h3><p>지켜보는 화물이 어디쯤 오는지 지도 하나로 봐요.</p>
        </li>
        <li>
          <a href="/about/shot-cargo.webp" target="_blank" rel="noreferrer" aria-label="화물 현황표 화면 크게 보기">
            <img src="/about/shot-cargo.webp" width={2224} height={1200} loading="lazy" alt="Marvia 화물 현황표 화면. 신용장과 B/L별로 출항, 입항, 입고 날짜와 포워더, 선사, 컨테이너가 한 줄씩 보여요."/>
          </a>
          <h3>화물 현황표</h3><p>신용장별 출항, 입항, 입고를 표로 한눈에 봐요.</p>
        </li>
      </ul>
    </section>

    {/* 마지막 권유: 브랜드 파랑 상자 + 사진 */}
    <section className="lp-wrap" id="start">
      <div className="lp-cta">
        <div className="lp-cta-text">
          <h2>지금 내 화물부터<br/>확인해 보세요</h2>
          <p>B/L 번호 하나면 충분해요.</p>
          <div className="lp-cta-action">{action}</div>
        </div>
        <img className="lp-cta-img" src="/landing/containers.jpg" width={900} height={1200} loading="lazy" alt=""/>
      </div>
      <p className="lp-scope"><Info size={14} strokeWidth={1.5} aria-hidden="true"/>부산항으로 들어오는 해상 수입 화물, 통관 단계 설명까지 지원해요. 세액이나 통관 가능 여부는 판단하지 않아요.{!isLive && ' 체험용 화면의 B/L, 선박, 위치, 시각은 모두 예시 값이에요.'}</p>
    </section>

    <div className="lp-wrap">{footer}</div>
  </div>;
}
