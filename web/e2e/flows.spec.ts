// 화면 주요 흐름 (계획 4b Task 9, C9): 질문→답·근거·화물, 실시간 계획, 선택지, 승인(고치기·거절).
// 가짜 API(e2e/fake_api.py)라 실제 모델 답이 아니다. 스크린샷에는 DEMO 번호만 있다.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const TOKEN = process.env.E2E_DEV_TOKEN ?? "e2e-token";
const outside: string[] = [];

test.beforeEach(async ({ page }) => {
  // [왜] 화면이 모델·임베딩 공급자에 닿지 않는지 센다. 닿으면 막고 적는다 (바깥 호출 0건)
  await page.route(/(anthropic\.com|voyageai\.com)/, (route) => {
    outside.push(route.request().url());
    return route.abort();
  });
  await page.goto("/");
  await page.getByLabel("개발 로그인 토큰").fill(TOKEN);
  await page.getByRole("button", { name: "들어가기" }).click();
});

test.afterAll(() => {
  expect(outside).toEqual([]);
});

async function ask(page: Page, text: string) {
  await page.getByLabel("질문이나 화물 단서 (B/L·화물관리번호)").fill(text);
  await page.locator("form.ask").getByRole("button", { name: "보내기" }).click();
}

async function accessible(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  const serious = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
}

const answers = (page: Page) => page.locator('.chat li[data-role="assistant"]');

test("질문하면 계획이 답보다 먼저 보이고, 답·근거·화물 카드가 뜬다", async ({ page }) => {
  await ask(page, "DEMO0001 언제까지 수입신고 해야 해요?");
  // 가짜 검색이 2초 늦다. 그동안 진행 중인 할 일이 보이고 답은 아직 없다 (실시간 계획)
  await expect(page.locator('.plan li[data-status="in_progress"]')).toBeVisible();
  expect(await answers(page).count()).toBe(0);
  await expect(answers(page)).toContainText("수입신고 기한과 근거");
  await expect(page.getByRole("heading", { name: "이렇게 읽었어요" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "DEMO0001" })).toBeVisible();
  await expect(page.getByText("시행일 2026-10-02")).toBeVisible();
  await expect(page.getByRole("link", { name: /원문 보기/ })).toHaveAttribute("href", /^https:\/\/www\.law\.go\.kr\//);
  await accessible(page);
  await page.screenshot({ path: "e2e/screenshots/answer.png", fullPage: true });
});

test("선택지 카드에서 고르면 이어서 답한다", async ({ page }) => {
  await ask(page, "장치기간이 궁금해요");
  await expect(page.getByRole("heading", { name: "어느 항구 기준으로 볼까요?" })).toBeVisible();
  await expect(page.getByRole("button", { name: /부산 \(권장\)/ })).toBeVisible();
  await accessible(page);
  await page.screenshot({ path: "e2e/screenshots/choice.png", fullPage: true });
  await page.getByRole("button", { name: /인천/ }).click();
  await expect(answers(page)).toContainText("확인한 내용을 정리했어요");
});

test("승인 카드에서 고친 값으로 저장한다", async ({ page }) => {
  await ask(page, "앞으로 자세히 설명해 줘");
  await expect(page.getByRole("heading", { name: "승인이 필요해요" })).toBeVisible();
  await accessible(page);
  await page.screenshot({ path: "e2e/screenshots/approval.png", fullPage: true });
  await page.getByLabel("고치기").check();
  await page.getByLabel("설명 깊이").selectOption("짧게");
  await page.locator(".card").getByRole("button", { name: "보내기" }).click();
  await expect(answers(page)).toContainText("설명 깊이 '짧게' 저장");
});

test("승인 카드에서 거절하면 하지 않는다", async ({ page }) => {
  await ask(page, "앞으로 자세히 설명해 줘");
  await page.getByLabel("거절").check();
  await page.locator(".card").getByRole("button", { name: "보내기" }).click();
  await expect(answers(page)).toContainText("확인한 내용을 정리했어요");
  await expect(answers(page)).not.toContainText("이번 차례에 한 일");
});
