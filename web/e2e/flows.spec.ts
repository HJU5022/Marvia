// 화면 주요 흐름 (계획 4b Task 9, C9): 질문→답·근거·화물, 실시간 계획, 선택지, 승인(고치기·거절).
// 가짜 API(e2e/fake_api.py)라 실제 모델 답이 아니다. 스크린샷에는 DEMO 번호만 있다.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const TOKEN = process.env.E2E_DEV_TOKEN ?? "e2e-token";
// 서버의 배 식별 스위치와 같은 값 (compose의 E2E_VESSEL, 계획 8b). off(기본)면 "배 식별" 묶음을 건너뛰고,
// on이면 그 묶음만 돈다. [왜] 켜면 화물 카드에 칸이 늘어 기존 그림(answer.png)이 달라진다. 기존 흐름은 off에서만 찍는다
const VESSEL = process.env.E2E_VESSEL === "on";
const outside: string[] = [];

test.beforeEach(async ({ page }, testInfo) => {
  test.skip(testInfo.titlePath.includes("배 식별") !== VESSEL, "E2E_VESSEL에 맞는 묶음만 돈다");
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

test.describe("배 식별", () => {
  const card = (page: Page, number: string) => page.locator(".cargo", { has: page.getByRole("heading", { name: number }) });

  test("배를 확정하면 화물 카드에 배와 판정 네 칸이 보인다", async ({ page }) => {
    await ask(page, "TESTVSL0001 어디쯤 왔어요?");
    await expect(answers(page)).toContainText("정리했어요");
    const cargo = card(page, "TESTVSL0001");
    await expect(cargo).toContainText("TEST CARGO A (호출부호 QQTST1 · 배 번호 999000001)");
    await expect(cargo.locator("dd[data-grade]")).toHaveText("순항");
    await expect(cargo).toContainText("일정 모름"); // 처음 알던 도착 예정을 받지 않아 지연을 보지 못했다
    await expect(cargo).toContainText("처음 알던 도착 예정이 없어 지연은 보지 못했어요");
    await expect(cargo).toContainText("판매 예정일을 받지 않아 여유 일수는 세지 않았어요");
    await expect(cargo).toContainText("확실");
    await expect(cargo).toContainText("해수부 입항 예정");
    await expect(cargo).not.toContainText("선박 위치 조회 뒤(2차)");
    await accessible(page);
    await page.screenshot({ path: "e2e/screenshots/vessel-confirmed.png", fullPage: true, mask: [page.locator(".cargo .meta")] });
  });

  test("같은 이름의 배가 여럿이면 선택 카드로 묻고, 고른 배로 판정한다", async ({ page }) => {
    await ask(page, "TESTVSL0002 어디쯤 왔어요?");
    await expect(page.getByRole("heading", { name: /TESTVSL0002 화물을 실은 배를 가리지 못했어요/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /모르겠어요 \(권장\)/ })).toBeVisible();
    await expect(card(page, "TESTVSL0002")).toContainText("배를 확인한 뒤에 보여 드려요");
    // 선택지의 이름과 설명은 서버가 자리표를 후보로 바꿔 채운다. 서류로 본 결과가 함께 보인다
    await expect(page.getByRole("button", { name: /호출부호 QQTST1 · 배 번호 999000001/ })).toContainText("MRN)로 찾은 입항 신고가 없어 서류로 확정하지 않았어요");
    await expect(page.locator(".card")).not.toContainText("{ship");
    await accessible(page);
    // [왜] "권장안으로 진행 (N초 뒤 자동)"의 초는 찍을 때마다 달라 마스크한다
    await page.screenshot({
      path: "e2e/screenshots/vessel-choice.png",
      fullPage: true,
      mask: [page.locator(".cargo .meta"), page.getByRole("button", { name: /권장안으로 진행/ })],
    });
    await page.getByRole("button", { name: /배 번호 999000001/ }).click();
    await expect(answers(page)).toContainText("정리했어요");
    await expect(card(page, "TESTVSL0002")).toContainText("고르신 배로 봤어요");
    await expect(card(page, "TESTVSL0002").locator("dd[data-grade]")).toHaveText("순항");
    await expect(card(page, "TESTVSL0002")).toContainText("호출부호를 맞춰 보지 못해 확신을 부분으로 낮췄어요");
  });

  test("호출부호가 같은 두 배는 자동 확정하지 않고, 고르면 확신이 부분이다", async ({ page }) => {
    await ask(page, "TESTVSL0007 어디쯤 왔어요?");
    await expect(page.getByRole("heading", { name: /TESTVSL0007 화물을 실은 배를 가리지 못했어요/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /배 번호 999000007/ })).toContainText("같은 호출부호의 배가 여럿이에요");
    await page.getByRole("button", { name: /배 번호 999000008/ }).click();
    await expect(answers(page)).toContainText("정리했어요");
    const cargo = card(page, "TESTVSL0007");
    await expect(cargo).toContainText("고르신 배로 봤어요");
    // [왜] dt와 dd 사이에 공백이 없어 "확신 확실"이라는 글은 화면에 없다. 확신 칸의 값을 직접 본다
    await expect(cargo.locator("dt", { hasText: "확신" }).locator("+ dd")).not.toHaveText("확실");
  });

  test("모르겠다고 하면 배 없이 진행하고 등급을 지어내지 않는다", async ({ page }) => {
    await ask(page, "TESTVSL0002 어디쯤 왔어요?");
    await page.getByRole("button", { name: /모르겠어요 \(권장\)/ }).click();
    await expect(answers(page)).toContainText("정리했어요");
    const cargo = card(page, "TESTVSL0002");
    await expect(cargo).toContainText("배를 모른다고 하셔서 배 없이 진행했어요");
    await expect(cargo.locator("dd[data-grade]")).toHaveText("등급 없음");
  });

  test("배에서 내린 화물은 배 위치를 보지 않았다고 말한다", async ({ page }) => {
    await ask(page, "TESTVSL0006 어디쯤 왔어요?");
    await expect(answers(page)).toContainText("정리했어요");
    const cargo = card(page, "TESTVSL0006");
    await expect(cargo).toContainText("배에서 내린 화물이라 배 위치는 보지 않았어요");
    await expect(cargo.locator("dd[data-grade]")).toHaveText("순항");
    await expect(cargo).not.toContainText("도착 예정");
  });

  test("배를 찾지 못하면 '등급 없음'과 그 까닭을 보인다", async ({ page }) => {
    await ask(page, "TESTVSL0003 어디쯤 왔어요?");
    await expect(answers(page)).toContainText("정리했어요");
    const cargo = card(page, "TESTVSL0003");
    await expect(cargo).toContainText("배 후보를 찾지 못했어요");
    await expect(cargo.locator("dd[data-grade]")).toHaveText("등급 없음");
    await expect(cargo).toContainText("도착 시각을 알 출처가 없어 등급을 내지 않았어요");
    await accessible(page);
    await page.screenshot({ path: "e2e/screenshots/vessel-no-grade.png", fullPage: true, mask: [page.locator(".cargo .meta")] });
  });
});

// 아래 기존 흐름은 스위치가 꺼진 서버에서만 돈다. 그림(answer·choice·approval.png)이 계획 8b 전과 같아야 한다
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
  // [왜] 조회 시각은 서버 시계라 매번 다르다. 가려서 그림이 같게 나오게 한다
  await page.screenshot({ path: "e2e/screenshots/answer.png", fullPage: true, mask: [page.locator(".cargo .meta")] });
});

test("선택지 카드에서 고르면 이어서 답한다", async ({ page }) => {
  await ask(page, "장치기간이 궁금해요");
  await expect(page.getByRole("heading", { name: "어느 항구 기준으로 볼까요?" })).toBeVisible();
  await expect(page.getByRole("button", { name: /부산 \(권장\)/ })).toBeVisible();
  await accessible(page);
  // [왜] "권장안으로 진행 (N초 뒤 자동)"의 초는 찍을 때마다 달라 마스크한다 (R-151)
  await page.screenshot({
    path: "e2e/screenshots/choice.png",
    fullPage: true,
    mask: [page.getByRole("button", { name: /권장안으로 진행/ })],
  });
  await page.getByRole("button", { name: /인천/ }).click();
  await expect(answers(page)).toContainText("확인한 내용을 정리했어요. 인천 기준이에요.");
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

test("409에는 서버가 보낸 까닭을 보이고, 지난 카드일 때만 카드를 치운다", async ({ page }) => {
  await ask(page, "장치기간이 궁금해요");
  const card = page.getByRole("heading", { name: "어느 항구 기준으로 볼까요?" });
  await expect(card).toBeVisible();
  // [왜] 앞 차례가 아직 잠금을 쥔 틈과 지난 카드는 가짜 API로 만들 수 없다. 서버가 보내는 409 본문을 흉내 낸다
  const refuse = (reason: object) =>
    page.route("**/agui", (route) =>
      route.fulfill({
        status: 409,
        contentType: "application/json",
        headers: { "access-control-allow-origin": new URL(page.url()).origin },
        body: JSON.stringify(reason),
      }),
    );
  await refuse({ error: "이 대화는 아직 답하는 중이에요" });
  await page.getByRole("button", { name: /인천/ }).click();
  const told = page.locator('p[role="alert"]'); // [왜] Next의 경로 안내(role=alert)와 겹치지 않게 화면 글만 본다
  await expect(told).toHaveText("이 대화는 아직 답하는 중이에요");
  await expect(card).toBeVisible();
  await page.unroute("**/agui");
  await refuse({ error: "답할 질문이 없거나 이미 지난 카드예요", code: "stale_card" });
  await page.getByRole("button", { name: /인천/ }).click();
  await expect(told).toHaveText("답할 질문이 없거나 이미 지난 카드예요");
  await expect(card).toBeHidden();
});

test("계정 삭제는 확인에 초점을 옮기고, 지운 뒤 다시 들어오면 대화가 비어 있다", async ({ page }) => {
  const threads: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/agui")) threads.push(JSON.parse(request.postData() ?? "{}").threadId);
  });
  await ask(page, "앞으로 자세히 설명해 줘");
  await expect(page.getByRole("heading", { name: "승인이 필요해요" })).toBeVisible();
  await page.getByRole("button", { name: "계정 삭제" }).click();
  await expect(page.getByRole("group", { name: "계정 삭제 확인" })).toBeFocused();
  await accessible(page);
  await page.getByRole("button", { name: "지우기" }).click();
  await expect(page.locator('p[role="alert"]')).toHaveText("계정을 지웠어요. 대화 기록과 저장한 값이 모두 지워졌어요");
  await page.getByLabel("개발 로그인 토큰").fill(TOKEN);
  await page.getByRole("button", { name: "들어가기" }).click();
  await expect(page.getByRole("heading", { name: "대화" })).toBeVisible();
  await expect(page.locator(".chat li")).toHaveCount(0); // 지운 계정의 대화가 남지 않는다
  await expect(page.locator(".card")).toHaveCount(0);
  await ask(page, "DEMO0001 언제까지 수입신고 해야 해요?");
  await expect(page.locator(".chat li")).not.toHaveCount(0);
  await expect.poll(() => threads.length).toBeGreaterThan(1); // 둘째 요청이 나간 뒤에 견준다
  expect(threads.at(-1)).not.toBe(threads[0]); // 지운 대화 id를 다시 쓰지 않는다
});

test("계정 삭제가 401이면 로그아웃한다", async ({ page }) => {
  // [왜] 토큰이 만료되면 서버가 401을 준다. 가짜 API의 개발 토큰은 만료되지 않아 응답을 흉내 낸다
  await page.route("**/account", (route) =>
    route.fulfill({ status: 401, headers: { "access-control-allow-origin": new URL(page.url()).origin } }),
  );
  await page.getByRole("button", { name: "계정 삭제" }).click();
  await page.getByRole("button", { name: "지우기" }).click();
  await expect(page.getByLabel("개발 로그인 토큰")).toBeVisible();
  await expect(page.locator('p[role="alert"]')).toHaveText("다시 로그인해 주세요");
});
