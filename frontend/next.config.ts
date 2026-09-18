import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // next dev 가 frontend/AGENTS.md, CLAUDE.md 를 만들지 않게 한다. AI 규칙은 루트 CLAUDE.md 하나다
  agentRules: false,
};

export default nextConfig;
