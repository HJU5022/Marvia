// 화면 그림 (계획 9): 가로 데스크톱(1280x800)과 휴대폰(390x844)에서 로그인, 빈 대화, 근거와 화물이 있는 답,
// 선택지 카드, 승인 카드를 찍고, v1 틀(40:60, 좁으면 시트)이 지켜지는지 본다. 가짜 API라 실제 모델 답이 아니고 DEMO 번호만 보인다.
// 배 식별 스위치가 켜진 실행에서는 돌지 않는다(화물 카드 칸이 달라 그림이 달라진다).
import AxeBuilder from "@axe-core/playwright";
import { expect, type Locator, type Page, test } from "@playwright/test";

const TOKEN = process.env.E2E_DEV_TOKEN ?? "e2e-token";
const BASE = process.env.E2E_BASE_URL ?? "http://web-e2e:3000";
const API = "http://api-e2e:8080";
const outside: string[] = [];

test.skip(process.env.E2E_VESSEL === "on", "그림은 스위치가 꺼진 서버에서만 찍는다");

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" }); // [왜] flows.spec.ts와 같다. 나타나는 움직임 중에 axe가 재지 않게 한다
  // [왜] 화면이 우리 화면 서버와 API 밖으로 요청을 보내지 않는지 센다(글꼴 서버, 모델, 임베딩 공급자)
  await page.route(/^https?:\/\//, (route) => {
    const origin = new URL(route.request().url()).origin;
    if (origin === new URL(BASE).origin || origin === API) return route.continue();
    outside.push(route.request().url());
    return route.abort();
  });
});

test.afterAll(() => {
  expect(outside).toEqual([]);
});

async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel("개발 로그인 토큰").fill(TOKEN);
  await page.getByRole("button", { name: "들어가기" }).click();
  await expect(page.getByRole("heading", { name: "대화" })).toBeAttached();
}

async function ask(page: Page, text: string) {
  await page.getByLabel("질문이나 화물 단서 (B/L·화물관리번호)").fill(text);
  await page.locator("form.ask").getByRole("button", { name: "보내기" }).click();
}

async function accessible(page: Page) {
  const result = await new AxeBuilder({ page }).analyze();
  const serious = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
}

// 눈에 보이는 맨 위 요소가 그 요소(또는 안쪽)인지: 시트 같은 것에 가려지지 않았는지 본다 (R-245)
async function uncovered(locator: Locator) {
  return locator.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.x + r.width / 2, r.y + Math.min(r.height / 2, 24));
    return !!top && (el === top || el.contains(top));
  });
}

// 옆으로 밀리는 화면이 없는지 (가로 스크롤 0)
async function noSideScroll(page: Page) {
  const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(wide).toBeLessThanOrEqual(0);
}

const SIZES = [
  { name: "desktop", viewport: { width: 1280, height: 800 } },
  { name: "phone", viewport: { width: 390, height: 844 } },
];

for (const { name, viewport } of SIZES) {
  test.describe(name, () => {
    test.use({ viewport });
    const shot = (page: Page, file: string, mask: ReturnType<Page["locator"]>[] = []) =>
      page.screenshot({ path: `e2e/screenshots/${name}-${file}.png`, mask });

    test("로그인 화면", async ({ page }) => {
      await page.goto("/");
      await expect(page.getByRole("heading", { name: "Marvia" })).toBeVisible();
      await noSideScroll(page);
      await accessible(page);
      await shot(page, "login");
    });

    test("빈 대화: 대화만 가운데에 있고 상세 칸은 없다", async ({ page }) => {
      await login(page);
      await expect(page.getByRole("heading", { name: "어떤 화물이 궁금하세요?" })).toBeVisible();
      await expect(page.locator("aside.detail-pane")).toHaveCount(0);
      await noSideScroll(page);
      await accessible(page);
      await shot(page, "empty");
    });

    test("근거와 화물이 있는 답", async ({ page }) => {
      await login(page);
      await ask(page, "DEMO0001 언제까지 수입신고 해야 해요?");
      await expect(page.locator('.chat li[data-role="assistant"]')).toContainText("수입신고 기한과 근거");
      // 휴대폰은 시트가 접혀 있어(손잡이를 눌러야 펼친다) 상세는 문서에 있기만 하면 된다
      const shown = viewport.width > 900 ? "toBeVisible" : "toBeAttached";
      await expect(page.locator("#evidence-title"))[shown]();
      await expect(page.locator(".cargo h3", { hasText: "DEMO0001" }))[shown]();
      await noSideScroll(page);
      await accessible(page);
      const boxes = await Promise.all(
        ["section.chat-pane", "aside.detail-pane"].map((selector) => page.locator(selector).boundingBox()),
      );
      if (viewport.width > 900) {
        // 데스크톱: 대화(왼쪽)와 상세(오른쪽)가 나란하다. 대화 칸은 clamp(380px, 40%, 720px)
        expect(boxes[0]!.x + boxes[0]!.width).toBeLessThanOrEqual(boxes[1]!.x + 1);
        expect(boxes[0]!.width).toBeGreaterThanOrEqual(380);
        expect(boxes[0]!.width).toBeLessThanOrEqual(720);
      } else {
        // 휴대폰: 상세는 아래에 손잡이 줄만 보이고(저절로 펼치지 않는다), 누르면 시트가 올라온다 (R-245)
        await expect(page.getByRole("button", { name: "상세 보기" })).toHaveAttribute("aria-expanded", "false");
        expect(await uncovered(page.getByLabel("질문이나 화물 단서 (B/L·화물관리번호)"))).toBe(true);
        await page.getByRole("button", { name: "상세 보기" }).click();
        await expect(page.getByRole("button", { name: "상세 접기" })).toHaveAttribute("aria-expanded", "true");
        const sheet = (await page.locator("aside.detail-pane").boundingBox())!;
        expect(sheet.y + sheet.height).toBeGreaterThanOrEqual(viewport.height - 1);
        expect(sheet.height).toBeLessThanOrEqual(Math.min(0.62 * viewport.height, 560) + 1); // v1 시트 높이
      }
      await shot(page, "answer", [page.locator(".cargo .meta")]);
      if (viewport.width <= 900) {
        // 입력창을 누르면 시트가 접혀 입력창이 가려지지 않는다
        const box = page.getByLabel("질문이나 화물 단서 (B/L·화물관리번호)");
        await box.focus();
        await expect(page.getByRole("button", { name: "상세 보기" })).toHaveAttribute("aria-expanded", "false");
        await expect(page.locator(".detail-body")).toBeHidden();
        await noSideScroll(page);
        await shot(page, "answer-sheet-folded", [page.locator(".cargo .meta")]);
        // 시트를 다시 펼친 채 엔터로 보내면 시트가 접히고 입력창이 보인다 (엔터는 초점을 옮기지 않는다)
        await page.getByRole("button", { name: "상세 보기" }).click();
        await box.fill("DEMO0001 다시 알려 주세요");
        await box.evaluate((el) => (el as HTMLTextAreaElement).focus({ preventScroll: true }));
        await page.keyboard.press("Enter");
        await expect(page.getByRole("button", { name: "상세 보기" })).toHaveAttribute("aria-expanded", "false");
        expect(await uncovered(box)).toBe(true);
      }
    });

    test("선택지 카드", async ({ page }) => {
      await login(page);
      await ask(page, "장치기간이 궁금해요");
      await expect(page.getByRole("heading", { name: "어느 항구 기준으로 볼까요?" })).toBeVisible();
      expect(await uncovered(page.locator(".card"))).toBe(true);
      await noSideScroll(page);
      await accessible(page);
      // [왜] "권장안으로 진행 (N초 뒤 자동)"의 초는 찍을 때마다 달라 마스크한다
      await shot(page, "choice", [page.getByRole("button", { name: /권장안으로 진행/ })]);
    });

    test("승인 카드", async ({ page }) => {
      await login(page);
      await ask(page, "앞으로 자세히 설명해 줘");
      await expect(page.getByRole("heading", { name: "승인이 필요해요" })).toBeVisible();
      expect(await uncovered(page.locator(".card"))).toBe(true);
      // 키보드 초점이 보인다: 라디오의 윤곽선을 지우지 않는다 (R-246)
      await page.keyboard.press("Shift");
      await page.getByLabel("거절").focus();
      const outline = await page.getByLabel("거절").evaluate((el) => getComputedStyle(el).outlineStyle);
      expect(outline).not.toBe("none");
      await noSideScroll(page);
      await accessible(page);
      await shot(page, "approval");
    });
  });
}
