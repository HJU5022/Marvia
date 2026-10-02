/** End-to-end acceptance for the current AI-composer home (10-02 rewrite; the old #bl form flow no longer exists).
 * 1) Demo mode: `npm run dev -- --port 3100` must be running at MARVIA_TEST_URL (default :3100). Fixtures only, no API.
 * 2) Live mode (optional): a production build made with NEXT_PUBLIC_API_BASE=http://127.0.0.1:3199 running at MARVIA_LIVE_TEST_URL.
 *    This script starts a fake API on :3199 itself, so the browser receives real SSE over the network (docs/specs/chat-progress.md).
 *    Without MARVIA_LIVE_TEST_URL the live checks are reported as SKIP, never as PASS.
 * Uses installed Chrome by default; PLAYWRIGHT_CHANNEL can override the browser channel.
 * All other off-origin HTTP is blocked and recorded: the app must run on local assets only.
 * Kept meaning from the previous script: 7 cargo states, axe WCAG A/AA, zero page errors and external HTTP, candidate validation,
 * MOF evidence filter, history filter + replay + retry isolation. Added: composer keys/IME/limits, real-stage waiting, drawers, roles.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import {chromium} from 'playwright';
import AxeBuilder from '@axe-core/playwright';

const base = process.env.MARVIA_TEST_URL ?? 'http://127.0.0.1:3100';
const live = process.env.MARVIA_LIVE_TEST_URL ?? '';
const MOCK_PORT = Number(process.env.MARVIA_MOCK_API_PORT ?? 3199);
const mockOrigin = `http://127.0.0.1:${MOCK_PORT}`;
const browser = await chromium.launch({channel: process.env.PLAYWRIGHT_CHANNEL ?? 'chrome', headless: true});
const failures = [], pageErrors = [], external = [], checks = [], skipped = [];
const interactionsOnly = process.argv.includes('--interactions');
fs.mkdirSync('screenshots', {recursive: true});
const check = (name, detail = {}) => { checks.push({name, ...detail}); console.log('PASS', name); };
const skip = (name, why) => { skipped.push({name, why}); console.log('SKIP', name, '-', why); };
async function ready(page) { await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(150); }
async function cargo(page, id) { await page.goto(`${base}/?fixture=${id}`); await page.locator('[data-testid="result"][aria-busy="false"]').waitFor(); await ready(page); }
// ?fixture= 없이 연다. 개발용 fixture 고정이 없어야 문장 속 예시 B/L대로 결과가 바뀐다 (lib/api.ts selectFixture)
async function home(page) { await page.goto(`${base}/`); await page.locator('[data-testid="result"][aria-busy="false"]').waitFor(); await ready(page); }
async function overflow(page, width) { const w = await page.evaluate(() => document.documentElement.scrollWidth); assert(w <= width, `overflow ${w}>${width}`); }
async function audit(page, name) {
  const results = await new AxeBuilder({page}).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  for (const v of results.violations) failures.push({page: name, id: v.id, impact: v.impact, nodes: v.nodes.map(n => ({target: n.target, summary: n.failureSummary}))});
}
async function newContext(width, allowed = [base]) {
  const context = await browser.newContext({viewport: {width, height: 1000}, deviceScaleFactor: 1, reducedMotion: 'reduce'});
  const origins = allowed.map(u => new URL(u).origin);
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.protocol.startsWith('http') && !origins.includes(url.origin)) { external.push(url.origin); return route.abort(); }
    return route.continue();
  });
  return context;
}
const turns = page => page.locator('.chat-turn').count();
const input = page => page.locator('#chat-input');
const activeId = page => page.evaluate(() => document.activeElement?.id ?? '');

/* ---------- Fake API for live mode (docs/specs/chat-progress.md AC-04, AC-05) ---------- */
const mockCalls = [];
const sleep = ms => new Promise(r => setTimeout(r, ms));
const chatReply = reply => ({kind: 'message', reply, agent: null, request: null, vessels: [], place: null, ports: [], days: null});
function startMock() {
  const server = http.createServer(async (req, res) => {
    const cors = {'access-control-allow-origin': req.headers.origin ?? '*', 'access-control-allow-headers': 'content-type, authorization, accept', 'access-control-allow-methods': 'GET, POST, PUT, DELETE'};
    if (req.method === 'OPTIONS') { res.writeHead(204, cors); return res.end(); }
    const url = new URL(req.url, mockOrigin);
    let body = '';
    for await (const chunk of req) body += chunk;
    const json = (status, data) => { res.writeHead(status, {...cors, 'content-type': 'application/json'}); res.end(JSON.stringify(data)); };
    mockCalls.push(`${req.method} ${url.pathname}`);
    if (url.pathname === '/api/me') return json(200, {user_id: 'u-test', email: null, is_operator: false, profile_complete: true});
    if (url.pathname === '/api/metrics') return json(403, {detail: '운영자만 쓸 수 있습니다.'});
    if (url.pathname === '/api/history') return json(200, {items: [], available: false});
    if (url.pathname === '/api/chat') return json(200, chatReply('대체 경로 답입니다.'));
    if (url.pathname === '/api/chat/stream') {
      const message = JSON.parse(body || '{}').message ?? '';
      if (message.includes('OLDSERVER')) return json(404, {detail: 'Not Found'});
      res.writeHead(200, {...cors, 'content-type': 'text/event-stream', 'cache-control': 'no-cache'});
      const send = (event, data) => res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
      send('progress', {stage: 'understand'}); await sleep(300);
      if (message.includes('BROKEN')) { send('error', {status: 500, detail: '답을 만드는 중 문제가 생겼습니다. 잠시 뒤 다시 시도해 주세요.'}); return res.end(); }
      res.write(': ping\n\n');
      send('progress', {stage: 'customs'}); await sleep(300);
      send('progress', {stage: 'identify'}); await sleep(2500);  // 화면이 진행 중 단계를 보여 주는 동안 기다린다
      send('result', chatReply('스트림 결과입니다.'));
      return res.end();
    }
    json(404, {detail: 'Not Found'});
  });
  return new Promise(resolve => server.listen(MOCK_PORT, '127.0.0.1', () => resolve(server)));
}

let mock;
try {
  /* ===== Demo mode: 7 cargo states and pages at two widths ===== */
  for (const width of [1440, 375]) {
    const context = await newContext(width);
    const page = await context.newPage(); page.on('pageerror', e => pageErrors.push(e.message));
    for (const [i, id] of (interactionsOnly ? [] : ['ok', 'partial', 'insufficient', 'failed', 'unsupported', 'watch', 'act']).entries()) {
      await cargo(page, id);
      assert.equal(await page.locator('[data-testid="result"]').getAttribute('data-status'), ['watch', 'act'].includes(id) ? 'ok' : id);
      if (['insufficient', 'failed', 'unsupported'].includes(id)) assert.equal(await page.locator('.verdict-hero').count(), 0, `${id}: no verdict card`);
      if (['watch', 'act'].includes(id)) assert.equal(await page.locator(`.verdict-hero.${id}`).count(), 1, `${id}: server verdict shown`);
      if (id === 'partial') assert.equal(await page.locator('.map-stale').count(), 1);
      if (['failed', 'unsupported'].includes(id)) assert.equal(await page.locator('.unknown-note').count(), 1, `${id}: unknown values stay empty`);
      if (['ok', 'partial', 'watch', 'act'].includes(id)) await page.locator('.leaflet-overlay-pane svg').waitFor();
      await overflow(page, width); await audit(page, `${id}-${width}`);
      await page.screenshot({path: `screenshots/${String(i + 1).padStart(2, '0')}-${id}-${width}.png`, fullPage: true}); check(`${id} ${width}px`);
    }
    for (const [i, route] of (interactionsOnly ? [] : ['history', 'metrics', 'settings', 'about', 'admin']).entries()) {
      await page.goto(`${base}/${route}`); if (route === 'history') await page.locator('tbody tr').first().waitFor(); await ready(page); await overflow(page, width); await audit(page, `${route}-${width}`);
      await page.screenshot({path: `screenshots/${String(i + 8).padStart(2, '0')}-${route}-${width}.png`, fullPage: true}); check(`${route} ${width}px`);
    }

    // AI 입력이 첫 화면의 중심이다: 입력창과 보내기 버튼이 스크롤 없이 보인다 (구현작업서 10절)
    await home(page);
    const box = await input(page).boundingBox(), send = await page.getByRole('button', {name: 'AI에게 질문 보내기'}).boundingBox();
    assert(box && send && box.y + box.height <= 1000 && send.y + send.height <= 1000, 'composer and send visible on first screen');
    assert.equal(await input(page).getAttribute('maxlength'), '500');
    check(`composer is the first-screen focus ${width}`);

    // 예시는 채우기만 한다. 한글 조합 중 Enter와 Shift+Enter는 보내지 않는다
    const before = await turns(page);
    await page.getByRole('button', {name: /중국에서 부산 들어오는 배/}).click();
    assert.equal(await input(page).inputValue(), '중국에서 부산 들어오는 배 보여줘'); assert.equal(await turns(page), before);
    await input(page).focus();
    await page.evaluate(() => document.getElementById('chat-input').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', isComposing: true, bubbles: true, cancelable: true})));
    await input(page).press('Shift+Enter');
    await page.waitForTimeout(300);
    assert.equal(await turns(page), before, 'IME Enter / Shift+Enter must not send'); assert.match(await input(page).inputValue(), /\n/);
    check(`example fills only, IME and Shift+Enter do not send ${width}`);

    // Enter 전송, 기다리는 동안 중복 전송 차단과 "이전 결과" 안내, 서버 판정 표시
    await input(page).fill('MRVDEMO1107 지금 조치해야 해?'); await input(page).press('Enter');
    await page.locator('.pending-card').waitFor();
    assert(await page.getByRole('button', {name: 'AI에게 질문 보내기'}).isDisabled());
    assert(await page.locator('.stale-notice').isVisible(), 'previous result is labelled while waiting');
    assert.equal(await page.locator('.pending-steps').count(), 0, 'demo has no server stages and must not invent them');
    await page.locator('[data-testid="result"][aria-busy="false"] .verdict-hero.act').waitFor();
    assert.equal(await turns(page), before + 2);
    check(`Enter sends, duplicate blocked, no invented stages ${width}`);

    // 움직임 줄이기: 결과 등장 애니메이션이 꺼진다
    assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('.result')).animationName), 'none');
    check(`reduced motion removes entrance animation ${width}`);

    // 아래로 내리면 입력창으로 돌아가는 버튼
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.getByRole('button', {name: 'AI에게 이어서 물어보기'}).click();
    assert.equal(await activeId(page), 'chat-input');
    check(`back-to-composer returns focus ${width}`);

    // 되묻기: 아무것도 고르지 않으면 막고, 후보를 고르면 정상 결과
    await cargo(page, 'insufficient'); await page.getByRole('button', {name: '확인하고 판정 진행'}).click(); assert(await page.locator('.candidate-section [role=alert]').isVisible());
    await page.getByRole('radio').first().check(); await page.getByRole('button', {name: '확인하고 판정 진행'}).click(); await page.locator('[data-status="ok"][aria-busy="false"]').waitFor();
    check(`candidate validation + resolution ${width}`);

    // 부분 결과: 해수부 근거만 보기는 화면 필터이고 새 판정이 아니다. 원본 값 펼침
    await cargo(page, 'partial'); await page.getByRole('button', {name: '해수부 근거만 보기'}).click(); assert(await page.locator('.filter-notice').isVisible());
    assert.equal(await page.locator('.evidence-source').filter({hasNotText: '해양수산부'}).count(), 0);
    await page.getByRole('button', {name: '전체 보기'}).click(); await page.locator('.evidence-item summary').first().click(); assert(await page.locator('.evidence-item pre').first().isVisible());
    check(`MOF filter + raw evidence ${width}`);

    // 지원 범위 밖: 질문 고치기는 입력창으로 보낸다 (예전 #bl 링크 대체)
    await cargo(page, 'unsupported'); await page.getByRole('button', {name: '질문 고치기'}).click(); assert.equal(await activeId(page), 'chat-input');
    check(`unsupported returns to composer ${width}`);

    // 입항 선박 검색 → 표 10열 → 선명 드로어 (포커스·inert·Esc·복귀, 여러 번 열고 닫아도 지도 정리)
    await home(page); await input(page).fill('중국에서 부산 들어오는 배 보여줘'); await input(page).press('Enter');
    await page.locator('.vessel-results').waitFor();
    assert.equal(await page.locator('.vessel-results thead th').count(), 10);
    for (let n = 0; n < 3; n++) {
      const link = page.locator('.ship-link').first();
      await link.click(); const dialog = page.getByRole('dialog'); await dialog.waitFor();
      assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), '패널 닫기');
      assert(await page.evaluate(() => document.querySelector('.app-shell').hasAttribute('inert')));
      if (n === 0) {
        await dialog.locator('.vessel-detail-info').waitFor();
        for (let t = 0; t < 25; t++) await page.keyboard.press('Tab');
        assert(await page.evaluate(() => !!document.activeElement?.closest('.drawer')), 'focus stays inside the drawer');
        if (width === 1440 && !interactionsOnly) await audit(page, `vessel-drawer-${width}`);
      }
      await page.keyboard.press('Escape'); await dialog.waitFor({state: 'detached'});
      assert.equal(await page.evaluate(() => document.activeElement?.className), 'ship-link');
    }
    assert.equal(await page.locator('.leaflet-container').count(), 0, 'vessel maps are removed after closing');
    check(`vessel search + drawer focus/inert/Esc/cleanup ${width}`);

    // 서류 사진: 드로어에서 확인한 값만 입력창에 넣고 자동으로 조회하지 않는다
    const turnCount = await turns(page);
    await page.getByRole('button', {name: '서류 사진에서 입력'}).click(); await page.getByRole('dialog').waitFor();
    const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=', 'base64');
    await page.locator('.drawer input[type=file]').setInputFiles({name: 'notice.png', mimeType: 'image/png', buffer: png});
    await page.getByRole('button', {name: '확인한 값으로 채우기'}).click(); await page.getByRole('dialog').waitFor({state: 'detached'});
    assert.match(await input(page).inputValue(), /MRVDEMO1101/); assert.equal(await turns(page), turnCount, 'document never sends by itself');
    check(`document drawer fills composer without sending ${width}`);

    // 이력: 필터, 저장된 판정 재생, 다시 조회해도 재생 스냅샷 조건 그대로
    await page.getByRole('link', {name: '조회 이력'}).first().click(); await page.locator('tbody tr').first().waitFor();
    await page.getByLabel('B/L 뒤 네 자리 검색').fill('ZZZZ'); assert.equal(await page.locator('tbody tr').count(), 0);
    await page.getByRole('button', {name: '필터 초기화'}).click(); await page.getByLabel('상태 필터').selectOption('failed');
    await page.getByRole('button', {name: /저장된 판정 열기/}).click(); await page.locator('[data-status="failed"]').waitFor();
    assert(await page.getByText('이력 재생', {exact: true}).isVisible());
    await page.getByRole('button', {name: '다시 조회', exact: true}).click(); await page.locator('[data-testid="result"][aria-busy="false"]').waitFor();
    assert.equal(await page.locator('[data-testid="result"]').getAttribute('data-status'), 'failed');
    check(`history filter + replay + retry isolation ${width}`);
    await context.close();
  }

  // 중간 폭: 가로 넘침 없음 (큰 표만 자기 칸에서 스크롤)
  for (const width of interactionsOnly ? [] : [1024, 768, 390]) {
    const context = await newContext(width); const page = await context.newPage(); page.on('pageerror', e => pageErrors.push(e.message));
    await cargo(page, 'ok'); await overflow(page, width); await page.screenshot({path: `screenshots/20-ok-${width}.png`, fullPage: true});
    await input(page).fill('중국에서 부산 들어오는 배 보여줘'); await input(page).press('Enter'); await page.locator('.vessel-results').waitFor(); await overflow(page, width);
    check(`no page overflow ${width}px (cargo + vessel table)`); await context.close();
  }

  /* ===== Live mode against the fake API: roles, real SSE stages, fallback, error ===== */
  if (!live) {
    skip('live mode (roles, SSE stages, fallback, error, history unavailable)', 'MARVIA_LIVE_TEST_URL not set');
  } else {
    mock = await startMock();
    for (const width of [1440, 375]) {
      const context = await newContext(width, [live, mockOrigin]); const page = await context.newPage(); page.on('pageerror', e => pageErrors.push(e.message));
      await page.goto(live); await input(page).waitFor(); await ready(page);
      assert.equal(await page.getByRole('link', {name: '평가 지표'}).count(), 0); assert.equal(await page.getByRole('link', {name: '관리'}).count(), 0);
      assert.equal(await page.locator('.feature-tiles button').count(), 3, 'first visit shows three real tasks');
      assert.equal(await page.locator('[data-testid="result"]').count(), 0, 'live mode never auto-runs a query');
      await overflow(page, width); if (!interactionsOnly) await audit(page, `live-home-${width}`);
      await page.screenshot({path: `screenshots/30-live-home-${width}.png`, fullPage: true});
      check(`live: user menu hides operator pages, idle first visit ${width}`);

      await page.goto(`${live}/metrics`); await page.getByText('운영자만 볼 수 있는 화면입니다.').waitFor();
      check(`live: direct /metrics is blocked for a normal user ${width}`);

      await page.goto(live); await input(page).waitFor();
      await input(page).fill('STREAM 테스트'); await input(page).press('Enter');
      await page.locator('.pending-steps li').nth(2).waitFor();
      const steps = await page.locator('.pending-steps li').evaluateAll(els => els.map(e => `${e.className}:${e.textContent.replace(/ (끝남|진행 중)$/, '')}`));
      assert.deepEqual(steps, ['done:질문 이해', 'done:통관 정보 조회', 'current:선박 식별'], 'only server stages, last one in progress');
      if (width === 1440) await page.screenshot({path: 'screenshots/31-live-stages-1440.png'});
      await page.locator('.chat-turn.assistant', {hasText: '스트림 결과입니다.'}).waitFor();
      assert.equal(await page.locator('.pending-card').count(), 0);
      check(`live: SSE stages appear as the server sends them ${width}`);

      const calls = mockCalls.filter(c => c === 'POST /api/chat').length;
      await input(page).fill('OLDSERVER 질문'); await input(page).press('Enter');
      await page.locator('.chat-turn.assistant', {hasText: '대체 경로 답입니다.'}).waitFor();
      assert.equal(mockCalls.filter(c => c === 'POST /api/chat').length, calls + 1, 'falls back to /api/chat once');
      check(`live: missing stream endpoint falls back to /api/chat ${width}`);

      await input(page).fill('BROKEN 질문'); await input(page).press('Enter');
      await page.locator('.chat-turn.assistant', {hasText: '답을 만드는 중 문제가 생겼습니다.'}).waitFor();
      assert.equal(await input(page).inputValue(), 'BROKEN 질문', 'input restored after an error');
      check(`live: stream error is shown and input restored ${width}`);

      await page.goto(`${live}/history`); await page.getByText('이력 저장소를 사용할 수 없습니다.').waitFor();
      check(`live: history available:false is not shown as empty ${width}`);
      await context.close();
    }
  }

  assert.deepEqual(pageErrors, [], 'Browser errors'); assert.deepEqual(external, [], 'Unexpected external HTTP');
  assert.equal(failures.length, 0, 'Accessibility violations: see screenshots/verification.json');
  console.log(`PASS: ${checks.length} checks, ${skipped.length} skipped; zero page errors and external HTTP requests. ${interactionsOnly ? 'Interaction-only run; accessibility not checked.' : 'Zero axe WCAG A/AA violations.'}`);
} finally {
  fs.writeFileSync('screenshots/verification.json', JSON.stringify({checks, skipped, accessibilityViolations: failures, pageErrors, externalRequests: external}, null, 2));
  mock?.close();
  await browser.close();
}
