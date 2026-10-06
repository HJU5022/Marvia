'use client';
/** Marvia 소개 본문 (10-07 정운 요청 25). 로그인 전 첫 화면(LoginScreen)과 사이드바의 /about 이 같은 본문을 쓴다. 디자인이 하나여야 해서 여기서만 짠다.
 * 디자인(10-07): imweb Reservation 테마(흰 바탕, 가는 글씨, 상자 없이 선과 여백) + K-Menu 랜딩(색 눈썹글, 큰 제목, 검은 버튼 하나, 01..04 단계).
 * 사진은 없다. 큰 그림 자리는 베이스맵 타일로 만든 틀(IntroBand)이고, 진짜 항구·선박 사진이 정해지면 그 자리에서 바꾼다.
 * 실제 있는 기능만 말한다. 평가 숫자는 측정 전이라 싣지 않는다 (평가는 운영자가 /metrics 에서 본다). 스타일은 app/styles/entry.css (intro-*).
 */
import {useEffect, useRef, type CSSProperties, type ReactNode} from 'react';
import {FileText, Layers3, Ship, ShieldCheck, Info} from 'lucide-react';
import {isLive} from '@/lib/api';

/** 어떻게 판단하나요 4단계. 제품이 실제로 하는 일만 적는다 (입력 → 배 확인 → 신호 비교 → 판정과 근거). */
const STEPS = [
  {icon: FileText, title: 'B/L 입력', text: 'B/L 번호 하나와 받아야 하는 날을 넣어요.'},
  {icon: Ship, title: '배 확인', text: '이름이 같아도 같은 배가 아닐 수 있어서, 확실하지 않으면 후보를 물어봐요.'},
  {icon: Layers3, title: '신호 비교', text: '선박 위치(AIS), 해수부 입항 예정, 통관 정보를 비교해요.'},
  {icon: ShieldCheck, title: '판정과 근거', text: '일정에 맞춰 판정하고 출처와 시각을 함께 보여줘요.'},
];

/** 판정 세 등급. 색은 점 하나로만 쓴다. 할 일은 이해를 돕는 예시다. */
const VERDICTS = [
  {cls: 'fine', name: '순항', mean: '확인된 근거에 이상 신호가 없어요', todo: '지금은 따로 할 일이 없어요.'},
  {cls: 'watch', name: '주의', mean: '서로 다르거나 오래된 정보가 있어요', todo: '포워더에게 선박 운항 상황과 입항 예정일을 확인하세요.'},
  {cls: 'act', name: '긴급', mean: '판매 일정이나 화물 진행을 바로 확인해야 해요', todo: '판매 일정을 조정할지 바로 정하세요.'},
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
    const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }), {threshold: .12, rootMargin: '0px 0px -6% 0px'});
    items.forEach(i => io.observe(i));
    return () => io.disconnect();
  }, []);
  return root;
}

const d = (i: number) => ({'--i': i} as CSSProperties);

/** 큰 그림 자리. 베이스맵 타일(public/basemap, z6)을 이어 붙인 틀이다. 사진 대신 쓰는 임시 자리라 캡션에 "예시"라고 적는다.
 * 타일이 없는 칸은 바다색 바탕이 보인다. 부산항 쪽을 가운데에 두고, 점선 경로는 장식이다 (실제 선박 위치 아님). */
function IntroBand({cols, rows, x0, y0, caption, tall}: {cols: number; rows: number; x0: number; y0: number; caption: string; tall?: boolean}) {
  const tiles: ReactNode[] = [];
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++)
    tiles.push(<img key={`${r}-${c}`} src={`/basemap/6/${x0 + c}/${y0 + r}.webp`} alt="" width={256} height={256} loading="lazy" onError={e => { e.currentTarget.style.visibility = 'hidden'; }}/>);
  return <figure className={`intro-band rv ${tall ? 'tall' : ''}`}>
    <div className="intro-band-tiles" style={{gridTemplateColumns: `repeat(${cols},1fr)`}} aria-hidden="true">{tiles}</div>
    <svg className="intro-band-route" viewBox="0 0 1000 400" preserveAspectRatio="none" aria-hidden="true">
      <path d="M40 90 C 260 60, 420 230, 640 250 S 860 270, 930 300" pathLength="1"/>
    </svg>
    <figcaption>{caption}</figcaption>
  </figure>;
}

/** nav: 맨 위 줄(로고와 로그인 자리). action: 큰 시작 버튼 (소개 페이지는 링크, 로그인 전 화면은 구글 로그인). */
export function IntroContent({action, nav, footer}: {action: ReactNode; nav?: ReactNode; footer?: ReactNode}) {
  const root = useReveal();
  return <div className="intro-page" ref={root}>
    {nav}
    <IntroBand cols={4} rows={2} x0={54} y0={24} caption="부산항으로 오는 화물 · 예시 지도"/>

    <section className="intro-hero">
      <p className="intro-eyebrow rv">IMPORT CARGO, MADE CLEAR</p>
      <h1 className="rv" style={d(1)}>내 수입 화물,<br/>지금 신경 써야 할까?</h1>
      <p className="intro-sub rv" style={d(2)}>B/L 하나로 내 화물이 제때 오는지 판정하고, 왜 그런지 근거까지 보여 드려요.</p>
      <div className="intro-action rv" style={d(3)}>{action}</div>
    </section>

    <section className="intro-section" aria-labelledby="intro-how">
      <p className="intro-eyebrow rv">HOW IT WORKS</p>
      <h2 id="intro-how" className="rv" style={d(1)}>어떻게 판단하나요</h2>
      <ol className="intro-steps">
        {STEPS.map(({icon: Icon, title, text}, i) => <li className="rv" style={d(i)} key={title}>
          <span className="intro-step-no">0{i + 1}</span>
          <Icon size={22} strokeWidth={1.4} aria-hidden="true"/>
          <h3>{title}</h3>
          <p>{text}</p>
        </li>)}
      </ol>
    </section>

    <figure className="intro-shot rv">
      <img src="/about/hero-result.webp" width={1432} height={1250} loading="lazy" alt="Marvia 조회 결과 화면. 지도에 선박 위치가 있고 주의 등급, 여유 4일, 출항지와 통관 단계가 보여요."/>
    </figure>

    <section className="intro-section" aria-labelledby="intro-verdict">
      <p className="intro-eyebrow rv">VERDICT</p>
      <h2 id="intro-verdict" className="rv" style={d(1)}>짧은 판정, 분명한 다음 행동</h2>
      <table className="intro-table rv" style={d(2)}>
        <thead><tr><th scope="col">등급</th><th scope="col">이럴 때</th><th scope="col">할 일 예시</th></tr></thead>
        <tbody>{VERDICTS.map(v => <tr key={v.name}>
          <th scope="row"><span className={`intro-dot ${v.cls}`} aria-hidden="true"/>{v.name}</th>
          <td data-label="이럴 때">{v.mean}</td>
          <td data-label="할 일 예시">{v.todo}</td>
        </tr>)}</tbody>
      </table>
      <p className="intro-note rv">근거가 모자라 판정할 수 없을 땐 판정 대신 추가 정보를 물어봐요.</p>
    </section>

    <section className="intro-section" aria-labelledby="intro-data">
      <p className="intro-eyebrow rv">ONE PLACE</p>
      <h2 id="intro-data" className="rv" style={d(1)}>흩어진 정보를 한곳에서 모아요</h2>
      <DataStrip/>
    </section>

    <IntroBand cols={4} rows={1} x0={54} y0={25} caption="통관 · 선박 위치 · 입항 예정을 한 지도에서 · 예시 지도" tall={false}/>

    <section className="intro-section" aria-labelledby="intro-shots">
      <p className="intro-eyebrow rv">SCREENS</p>
      <h2 id="intro-shots" className="rv" style={d(1)}>이런 화면으로 보여 드려요</h2>
      <ul className="intro-shots">
        <li className="rv" style={d(0)}>
          <img src="/about/shot-watch.webp" width={2224} height={1530} loading="lazy" alt="지켜보는 화물 지도 화면. 부산항 쪽으로 오는 선박과 이동 경로가 지도에 있고, 오른쪽에 화물 목록과 판정 등급이 있어요."/>
          <h3>지켜보는 화물 지도</h3><p>지켜보는 화물이 어디쯤 오는지 지도 하나로 봐요.</p>
        </li>
        <li className="rv" style={d(1)}>
          <img src="/about/shot-cargo.webp" width={2224} height={1236} loading="lazy" alt="Marvia 화물 현황표 화면. 신용장과 B/L별로 출항, 입항, 입고 날짜와 포워더, 선사, 컨테이너가 한 줄씩 보여요."/>
          <h3>화물 현황표</h3><p>신용장별 출항, 입항, 입고를 표로 한눈에 봐요.</p>
        </li>
      </ul>
    </section>

    <section className="intro-final rv">
      <p className="intro-eyebrow">GET STARTED</p>
      <h2>지금 내 화물부터 확인해 보세요</h2>
      <div className="intro-action">{action}</div>
      <p className="intro-scope"><Info size={14} aria-hidden="true"/>부산항으로 들어오는 해상 수입 화물, 통관 단계 설명까지 지원해요.{!isLive && ' 체험용 화면의 B/L, 선박, 위치, 시각은 모두 예시 값이에요.'}</p>
    </section>
    {footer}
  </div>;
}

/** 정보가 모이는 띠: 세 출처 → Marvia → 판정. 넓은 화면은 가로, 좁은 화면은 세로로 쌓인다. 글자만으로 읽히는 표 같은 그림이다. */
function DataStrip() {
  return <div className="intro-strip rv" role="img" aria-label="관세청 UNI-PASS의 통관 정보, 선박 위치 신호, 해수부 입항 예정 세 가지를 Marvia가 모아 비교하고, 순항 주의 긴급 중 하나로 판정해요.">
    <ul className="intro-strip-src">
      <li><b>통관 정보</b><span>관세청 UNI-PASS</span></li>
      <li><b>선박 위치</b><span>위치 신호(AIS)</span></li>
      <li><b>입항 예정</b><span>해양수산부</span></li>
    </ul>
    <span className="intro-strip-arrow" aria-hidden="true"/>
    <div className="intro-strip-core"><b>Marvia</b><span>비교하고 근거 찾기</span></div>
    <span className="intro-strip-arrow" aria-hidden="true"/>
    <ul className="intro-strip-out">
      {VERDICTS.map(v => <li key={v.name}><span className={`intro-dot ${v.cls}`}/>{v.name}</li>)}
    </ul>
  </div>;
}
