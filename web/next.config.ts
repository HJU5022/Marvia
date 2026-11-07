// 화면 설정 (설계 10절, 계획 4b Task 7). standalone: Docker 실행 단계에 필요한 파일만 .next/standalone에 모은다
import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
};

export default config;
