// Standalone delivery uses local fonts/geography; no external services are configured.
import type { NextConfig } from 'next';
const config: NextConfig = { reactStrictMode: true, agentRules: false, devIndicators: false };
export default config;
