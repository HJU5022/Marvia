// 화면 틀 (설계 10절, 계획 9). 글꼴은 패키지에서 직접 싣는다(빌드·e2e가 바깥 글꼴 서버에 기대지 않는다).
// 영문·숫자는 Manrope, 한글은 Noto Sans KR, 고정폭 IBM Plex Mono는 B/L·컨테이너 번호에만 쓴다.
import "@fontsource-variable/manrope";
import "@fontsource-variable/noto-sans-kr";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./globals.css";

import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = { title: "Marvia", description: "수입 화물과 법령 근거를 함께 보는 에이전트" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
