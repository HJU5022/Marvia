// 배 식별 선택 카드가 좁은 화면의 상세 시트에 가려지지 않는지 본다 (계획 9, R-245).
// 화물 카드(상세)와 선택 카드가 함께 오는 경우라 배 식별 스위치가 켜진 실행(E2E_VESSEL=on)에서만 돈다.
import { expect, test } from "@playwright/test";

const TOKEN = process.env.E2E_DEV_TOKEN ?? "e2e-token";

test.skip(process.env.E2E_VESSEL !== "on", "배 식별 스위치가 켜진 실행에서만 돈다");
test.use({ viewport: { width: 390, height: 844 } });

test("휴대폰 폭에서 화물 카드와 함께 온 선택 카드가 시트에 가려지지 않는다", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByLabel("개발 로그인 토큰").fill(TOKEN);
  await page.getByRole("button", { name: "들어가기" }).click();
  await page.getByLabel("질문이나 화물 단서 (B/L·화물관리번호)").fill("TESTVSL0002 어디쯤 왔어요?");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: /TESTVSL0002 화물을 실은 배를 가리지 못했어요/ })).toBeVisible();
  // 상세(화물 카드)는 있고 시트는 접혀 있다
  await expect(page.getByRole("button", { name: "상세 보기" })).toHaveAttribute("aria-expanded", "false");
  const covered = await page.locator(".card").evaluate((el) => {
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.x + r.width / 2, r.y + Math.min(r.height / 2, 24));
    return !(top && (el === top || el.contains(top)));
  });
  expect(covered).toBe(false);
  // 카드에서 고르면 이어서 답하고, 이때도 시트가 저절로 펼쳐지지 않는다
  await page.getByRole("button", { name: /모르겠어요 \(권장\)/ }).click();
  await expect(page.locator('.chat li[data-role="assistant"]')).toContainText("정리했어요");
  await expect(page.getByRole("button", { name: "상세 보기" })).toHaveAttribute("aria-expanded", "false");
});
