// Playwright 설정 (계획 4b Task 9). compose e2e 망 안에서 돈다: 화면 http://web-e2e:3000, API http://api-e2e:8080
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  // [왜] 가짜 API는 대화마다 따로지만 화면 하나를 함께 쓴다. 깜빡이는 실패를 숨기지 않게 다시 돌리지 않는다
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://web-e2e:3000",
    locale: "ko-KR",
    timezoneId: "Asia/Seoul",
    viewport: { width: 1000, height: 1400 },
  },
});
