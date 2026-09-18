// 카카오 지도 JS SDK 로더. autoload=false 로 스크립트를 한 번만 넣고 kakao.maps.load 로 초기화한다.
// 키는 NEXT_PUBLIC_KAKAO_JS_KEY 하나만 쓴다. 카카오 콘솔에 도메인(localhost:3000, Vercel)이 등록돼 있어야 지도가 뜬다.

/* eslint-disable @typescript-eslint/no-explicit-any */
declare global {
  interface Window {
    kakao: any;
  }
}

export type Kakao = any;

const SDK_ID = "kakao-maps-sdk";
let loading: Promise<Kakao> | null = null;

export function loadKakao(): Promise<Kakao> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("브라우저에서만 지도를 불러올 수 있습니다"));
  }
  if (loading) return loading;

  const key = process.env.NEXT_PUBLIC_KAKAO_JS_KEY;
  if (!key) {
    return Promise.reject(new Error("NEXT_PUBLIC_KAKAO_JS_KEY 가 없습니다 (frontend/.env.local)"));
  }

  loading = new Promise<Kakao>((resolve, reject) => {
    const ready = () => window.kakao.maps.load(() => resolve(window.kakao));

    if (window.kakao?.maps) {
      ready();
      return;
    }
    let script = document.getElementById(SDK_ID) as HTMLScriptElement | null;
    if (!script) {
      script = document.createElement("script");
      script.id = SDK_ID;
      script.async = true;
      script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(key)}&autoload=false`;
      document.head.appendChild(script);
    }
    script.addEventListener("load", ready);
    script.addEventListener("error", () => {
      loading = null;
      reject(new Error("지도 SDK 를 불러오지 못했습니다. 카카오 콘솔에 현재 도메인이 등록됐는지 확인하세요"));
    });
  });
  return loading;
}

// 핀 모양. SVG 를 data URL 로 만들어 MarkerImage 에 넣는다.

export type PinShape = "drop" | "square" | "circle";

export interface PinStyle {
  fill: string;
  stroke: string;
  label: string; // 핀 안에 들어가는 한두 글자
  shape: PinShape;
}

function pinSvg({ fill, stroke, label, shape }: PinStyle): string {
  const text = `<text x="16" y="17" text-anchor="middle" dominant-baseline="middle" font-family="sans-serif" font-size="11" font-weight="700" fill="#fff">${label}</text>`;
  let body: string;
  if (shape === "square") {
    body = `<rect x="3" y="3" width="26" height="26" rx="5" fill="${fill}" stroke="${stroke}" stroke-width="2"/><path d="M12 29 L16 38 L20 29 Z" fill="${fill}" stroke="${stroke}" stroke-width="2" stroke-linejoin="round"/>`;
  } else if (shape === "circle") {
    body = `<circle cx="16" cy="16" r="10" fill="${fill}" stroke="${stroke}" stroke-width="2.5"/>`;
  } else {
    body = `<path d="M16 38 C16 38 3 22 3 15 A13 13 0 0 1 29 15 C29 22 16 38 16 38 Z" fill="${fill}" stroke="${stroke}" stroke-width="2"/>`;
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="40" viewBox="0 0 32 40">${body}${text}</svg>`;
}

const imageCache = new Map<string, Kakao>();

export function pinImage(kakao: Kakao, style: PinStyle): Kakao {
  const svg = pinSvg(style);
  const cached = imageCache.get(svg);
  if (cached) return cached;
  const size = new kakao.maps.Size(32, 40);
  const offset =
    style.shape === "circle" ? new kakao.maps.Point(16, 16) : new kakao.maps.Point(16, 38);
  const image = new kakao.maps.MarkerImage(
    `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`,
    size,
    { offset },
  );
  imageCache.set(svg, image);
  return image;
}

// 핀 위 이름표. CustomOverlay 로 붙인다.
export function nameLabel(kakao: Kakao, map: Kakao, lng: number, lat: number, text: string): Kakao {
  const el = document.createElement("div");
  el.className = "pin-label";
  el.textContent = text;
  return new kakao.maps.CustomOverlay({
    map,
    position: new kakao.maps.LatLng(lat, lng),
    content: el,
    yAnchor: 2.9,
    zIndex: 3,
  });
}
