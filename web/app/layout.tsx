// 화면 틀 (설계 10절). 한글 글꼴은 패키지에서 직접 싣는다(빌드·e2e가 바깥 글꼴 서버에 기대지 않는다).
import "@fontsource-variable/noto-sans-kr";
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
