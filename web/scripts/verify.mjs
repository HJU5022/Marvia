/** End-to-end acceptance for the current AI-composer home (rewritten; the old #bl form flow no longer exists).
 * 1) Demo mode: `npm run dev -- --port 3100` must be running at MARVIA_TEST_URL (default http://localhost:3100; 127.0.0.1 makes the Next dev server block dev resources, so the first step times out). Fixtures only, no API.
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

const SHOTS77 = process.env.MARVIA_SHOT_DIR ?? 'screenshots';  // 스크린샷 자리
const base = process.env.MARVIA_TEST_URL ?? 'http://localhost:3100';
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
  // 지도 바탕(OpenFreeMap)이 쓰는 호스트 하나만 예외로 허용한다. 스타일, 벡터 타일, 글꼴, 아이콘이 모두 이 호스트다.
  // 못 불러와도 지도는 해안선으로 되돌아가야 하므로(lib/basemap.ts) 이 허용이 e2e를 네트워크에 묶지는 않는다. 다른 외부 주소는 그대로 실패시킨다.
  const origins = [...allowed.map(u => new URL(u).origin), 'https://tiles.openfreemap.org'];
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
/** 선박 검색 답. 서버 _ship_list_lines와 같은 모양의 글 + 43척(항구 40곳)의 구조 데이터 */
function vesselReply() {
  const vessels = Array.from({length: 43}, (_, i) => ({ship_name: `TEST VESSEL ${i + 1}`, call_sign: `T${i}`, nationality: 'PANAMA', ship_kind: '컨테이너선', previous_port: `PORT ${i % 40}`, next_port: null, purpose: '양하',
    expected_arrival: new Date(Date.UTC(2026, 9, 6, 15 + i, 0)).toISOString(), facility: null, planned_departure: null, is_cargo: true}));
  const lines = vessels.slice(0, 5).map(v => `· ${v.ship_name} · 10월 ${7 + Math.floor(Number(v.ship_name.split(' ')[2]) / 24)}일 00:00 도착 예정 · ${v.previous_port}`);
  return {kind: 'vessels', reply: ['일본에서 1주 안에 부산 오는 수입 화물선 43척이에요.', ...lines, '외 38척', '해수부 입항 신고의 직전 기항지 기준이에요.'].join('\n'),
    agent: null, request: null, vessels, place: 'JP', ports: Array.from({length: 40}, (_, i) => `PORT ${i}`), days: 7};
}
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
      send('result', message.includes('VESSELS') ? vesselReply() : chatReply('스트림 결과입니다.'));
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
      await page.goto(`${base}/${route}`); if (route === 'history') await page.locator('.hist-list > li').first().waitFor(); await ready(page); await overflow(page, width); await audit(page, `${route}-${width}`);
      await page.screenshot({path: `screenshots/${String(i + 8).padStart(2, '0')}-${route}-${width}.png`, fullPage: true}); check(`${route} ${width}px`);
    }

    // 설정은 화면 안 탭 4개 (조회 이력 탭을 뺐다), 관리는 탭 2개: 탭마다 접근성 검사 (탭을 바꿔도 가로 넘침이 없어야 한다)
    await page.goto(`${base}/settings`); await ready(page);
    const settingsTabs = page.locator('.st-tabs .st-tab'); assert.equal(await settingsTabs.count(), 4, 'settings has 4 in-page tabs');
    for (let t = 0; t < 4; t++) { await settingsTabs.nth(t).click(); await ready(page); await overflow(page, width); if (!interactionsOnly) await audit(page, `settings-tab${t}-${width}`); }
    await page.goto(`${base}/admin`); await ready(page);
    const adminTabs = page.getByRole('tab'); assert.equal(await adminTabs.count(), 2, 'admin has 2 in-page tabs');
    for (let t = 0; t < 2; t++) { await adminTabs.nth(t).click(); await ready(page); await overflow(page, width); if (!interactionsOnly) await audit(page, `admin-tab${t}-${width}`); }
    check(`settings 5 tabs + admin 2 tabs ${width}`);

    // AI 입력이 첫 화면의 중심이다: 입력창과 보내기 버튼이 스크롤 없이 보인다 (구현작업서 10절)
    await home(page);
    const box = await input(page).boundingBox(), send = await page.getByRole('button', {name: 'AI에게 질문 보내기'}).boundingBox();
    assert(box && send && box.y + box.height <= 1000 && send.y + send.height <= 1000, 'composer and send visible on first screen');
    assert.equal(await input(page).getAttribute('maxlength'), '500');
    check(`composer is the first-screen focus ${width}`);

    // 한글 조합 중 Enter와 Shift+Enter는 보내지 않는다. (예시 문장 채우기는 대화가 빈 첫 화면에만 있고, 데모는 첫 화면에 결과를 자동으로 열어 그 화면이 없다 → live 블록에서 확인)
    const before = await turns(page);
    await input(page).focus();
    await input(page).fill('MRVDEMO1101');
    await page.evaluate(() => document.getElementById('chat-input').dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', isComposing: true, bubbles: true, cancelable: true})));
    await input(page).press('Shift+Enter');
    await page.waitForTimeout(300);
    assert.equal(await turns(page), before, 'IME Enter / Shift+Enter must not send'); assert.match(await input(page).inputValue(), /\n/);
    check(`IME Enter and Shift+Enter do not send ${width}`);

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

    // 입력창은 항상 아래에 고정된다: 대화 칸을 맨 아래로 내려도, 페이지는 스크롤되지 않아도 입력창이 보이고 "이어서 물어보기" 버튼은 필요 없다
    await page.evaluate(() => document.querySelector('.chat-scroll').scrollTo(0, document.querySelector('.chat-scroll').scrollHeight));
    const pinned = await input(page).boundingBox(), vh = page.viewportSize().height;
    assert(pinned && pinned.y >= 0 && pinned.y + pinned.height <= vh, 'composer stays visible while the conversation is scrolled');
    assert.equal(await page.getByRole('button', {name: 'AI에게 이어서 물어보기'}).count(), 0, 'no back-to-composer button when composer is pinned');
    if (width === 1440) assert(await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight + 1), 'page itself does not scroll at 1440x1000');
    await input(page).focus(); assert.equal(await activeId(page), 'chat-input');
    check(`composer stays pinned, no back-to-composer button ${width}`);

    // 되묻기: 아무것도 고르지 않으면 막고, 후보를 고르면 정상 결과
    await cargo(page, 'insufficient'); await page.getByRole('button', {name: '확인하고 판정하기'}).click(); assert(await page.locator('.candidate-section [role=alert]').isVisible());
    await page.locator('.cand-row').first().click(); assert(await page.getByRole('radio').first().isChecked(), 'clicking a candidate row selects its radio'); await page.getByRole('button', {name: '확인하고 판정하기'}).click(); await page.locator('[data-status="ok"][aria-busy="false"]').waitFor();
    check(`candidate validation + resolution ${width}`);

    // 채팅으로 조회해 되묻는 답이 오면 말풍선 아래에 후보 칩이 보이고, 칩을 누르면 같은 요청으로 판정이 나온 뒤 칩은 사라진다
    await home(page); await input(page).fill('MRVDEMO1102'); await input(page).press('Enter');
    await page.locator('.chat-cand-chips').waitFor();
    assert(await page.locator('.chat-cand-chip').count() > 0, 'candidate chips appear under the asking bubble');
    await page.locator('.chat-cand-chip').first().click();
    await page.locator('[data-status="ok"][aria-busy="false"]').waitFor();
    assert.equal(await page.locator('.chat-cand-chips').count(), 0, 'chips disappear once resolved');
    check(`chat candidate chips resolve ${width}`);

    // 데모의 정상 답에는 모의 근거 표시가 붙는다. 칩을 누르면 그 자리에 출처가 뜨고, Esc로 닫으면 칩으로 포커스가 돌아온다. "근거 N개"는 모음 패널을 연다
    await home(page); await input(page).fill('MRVDEMO1101'); await input(page).press('Enter');
    const chip = page.locator('.chat-turn.assistant .ev-chip').first();
    await chip.waitFor();
    await chip.click();
    const pop = page.locator('.ev-pop');
    await pop.waitFor();
    assert((await pop.innerText()).includes('해수부'), 'popover shows the source label');
    assert.equal(await page.locator('.chat-turn.assistant .ev-chip').count(), 1, 'two marks in one sentence merge into one chip');
    assert.match(await chip.innerText(), /해수부 외 1/, 'merged label is first source plus count');
    assert.equal(await pop.locator('.ev-pop-item').count(), 2, 'one section per source');
    assert.equal(await page.evaluate(() => getComputedStyle(document.querySelector('.ev-pop')).borderRadius), '0px', 'popover is a plain square box');
    await page.keyboard.press('Escape');
    assert.equal(await pop.count(), 0, 'Esc closes the popover');
    assert.equal(await page.evaluate(() => document.activeElement?.classList.contains('ev-chip')), true, 'focus returns to the chip');
    await page.getByRole('button', {name: /근거 \d+개/}).click();
    await page.getByRole('dialog', {name: '이 대화의 근거 모음'}).waitFor();
    assert((await page.locator('.ev-collect').innerText()).includes('해수부'), 'collection panel lists the source');
    await page.keyboard.press('Escape');
    check(`evidence chip popover + collection panel ${width}`);

    // 부분 결과: 해수부 근거만 보기는 화면 필터이고 새 판정이 아니다. 원본 값 펼침
    await cargo(page, 'partial'); await page.getByRole('button', {name: '해수부 근거만 보기'}).click(); await page.locator('.more-fold[open] .filter-notice').waitFor({state: 'visible', timeout: 3000}); // 근거는 접힌 "펼쳐 보기" 안에 있어, 필터가 펼치고 안내를 보인다
    assert(await page.locator('.filter-notice').isVisible());
    assert.equal(await page.locator('.evidence-source').filter({hasNotText: '해양수산부'}).count(), 0);
    await page.getByRole('button', {name: '전체 보기'}).click(); await page.locator('.evidence-item summary').first().click(); assert(await page.locator('.evidence-item .evidence-detail').first().isVisible());
    check(`MOF filter + raw evidence ${width}`);

    // 지원 범위 밖: 질문 고치기는 입력창으로 보낸다 (예전 #bl 링크 대체)
    await cargo(page, 'unsupported'); await page.getByRole('button', {name: '질문 고치기'}).click(); assert.equal(await activeId(page), 'chat-input');
    check(`unsupported returns to composer ${width}`);

    // 입항 선박 검색 → 표 5열 → 선명을 누르면 표 아래 카드(드로어 아님)가 그 배로 바뀐다. 여러 번 바꿔도 지도는 하나만 남는다
    await home(page); await input(page).fill('중국에서 부산 들어오는 배 보여줘'); await input(page).press('Enter');
    await page.locator('.vessel-results').waitFor();
    assert.equal(await page.locator('.vessel-results thead th').count(), 5);
    // 체험 모드 답도 3칸 표로 (배 이름 | 도착 예정 | 직전 기항지), 직전 기항지 2곳은 접지 않고 바로 보인다
    assert((await page.locator('.cvt-list li').count()) >= 1, 'one-line list rows'); assert.equal(await page.locator('.cvt-table').count(), 0, 'no boxed table');
    assert.equal(await page.locator('.vl-ports details, details.vl-ports').count(), 0, 'few ports are shown inline, no disclosure');
    assert.equal(await page.locator('.vl-ports-line .vl-chips li').count(), 2);
    await overflow(page, width);
    await page.screenshot({path: `${SHOTS77}/demo-vessel-${width}.png`});
    // 휴대폰: 상세는 아래 시트다. 입력창에 포커스가 있으면 접혀 있어서 손잡이로 편다
    const handle = page.locator('.sheet-handle');
    if (await handle.isVisible() && (await handle.getAttribute('aria-expanded')) === 'false') await handle.click();
    const links = page.locator('.ship-link'); assert((await links.count()) >= 2, 'at least two vessels to switch between');
    for (let n = 0; n < 4; n++) {
      const link = links.nth(n % 2), name = (await link.textContent()).trim();
      await link.click();
      await page.locator('.vessel-results .vd .vessel-detail-info').waitFor();
      assert.equal(await page.locator('.vd-head h3').textContent(), name, 'inline detail follows the clicked vessel');
      assert.equal(await link.getAttribute('aria-pressed'), 'true');
      assert.equal(await page.getByRole('dialog').count(), 0, 'vessel detail is inline, not a dialog');
      assert(!(await page.evaluate(() => document.querySelector('.app-shell')?.hasAttribute('inert'))), 'page is not inert for an inline card');
      if (n === 0 && width === 1440 && !interactionsOnly) await audit(page, `vessel-detail-${width}`);
    }
    await page.locator('.vd-more summary').click(); await page.locator('.vd-more dl').waitFor({state: 'visible', timeout: 3000}); // 펼침 애니메이션 때문에 즉시 확인하지 않고 기다린다
    assert(await page.locator('.vd-more[open] dl').isVisible(), 'detail 펼쳐 보기 opens');
    assert(await page.locator('.vessel-results .leaflet-container').count() <= 1, 'only the selected vessel keeps a map');
    check(`vessel search + inline detail switch/cleanup ${width}`);

    // 서류 첨부: 붙이면 칩만 생기고 아무 일도 없다(읽기·조회 없음). 보내기를 눌러야 서류에서 B/L만 읽어 조회한다.
    // 입력창은 셋 다 된다: 글만, 사진만, 사진 + 글. 보낼 때마다 사용자 말풍선은 정확히 한 개이고 조회 결과가 온다. 확인 카드·수정 화면은 없다
    const turnCount = await turns(page);
    // 휴대폰: 펼친 상세 시트가 입력창을 덮으므로 손잡이로 접는다 (넓은 화면에는 손잡이가 없다)
    if (await handle.isVisible() && (await handle.getAttribute('aria-expanded')) === 'true') await handle.click();
    assert(await page.getByRole('button', {name: '서류 사진·PDF 첨부'}).isVisible(), 'attach button in composer');
    const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=', 'base64');
    const sendBtn = page.getByRole('button', {name: 'AI에게 질문 보내기'});
    const userTurns = () => page.locator('.chat-turn.user').count();
    const attachPng = () => page.locator('.ask input[type=file]').first().setInputFiles({name: 'notice.png', mimeType: 'image/png', buffer: png});
    const settle = () => page.waitForFunction(() => !document.querySelector('.pending-card'), null, {timeout: 20000});
    // (1) 사진만: 칩만 생기고 턴은 늘지 않는다. 보내기 버튼은 글이 없어도 켜진다
    await input(page).fill('');
    assert(await sendBtn.isDisabled(), 'send is disabled with nothing to send');
    await attachPng();
    await page.locator('.doc-chip').waitFor();
    assert.equal(await page.locator('#chat-input').isDisabled(), false, 'composer stays enabled with a document attached');
    await page.waitForTimeout(1200);
    assert.equal(await turns(page), turnCount, 'attaching a document adds no turn (no background reading)');
    assert.equal(await page.locator('.document-result, .document-status').count(), 0, 'no confirmation card');
    assert(await sendBtn.isEnabled(), 'send is enabled for a photo with no text');
    if (width === 1440 && !interactionsOnly) await audit(page, `document-attach-${width}`);
    // 칩의 X는 서류를 뗀다
    await page.getByRole('button', {name: '첨부한 서류 빼기'}).click(); await page.locator('.doc-chip').waitFor({state: 'detached'});
    await attachPng(); await page.locator('.doc-chip').waitFor();
    let sentFrom = await userTurns();
    await sendBtn.click();
    await page.waitForFunction(n => document.querySelectorAll('.chat-turn.user').length === n, sentFrom + 1, {timeout: 15000});
    await settle();
    assert.equal(await userTurns(), sentFrom + 1, 'photo only: exactly one user turn');
    const photoBubble = await page.locator('.chat-turn.user').last().textContent();
    assert(photoBubble.includes('notice.png'), 'photo-only bubble shows the file name');
    assert(!/MRVDEMO\d{4}/.test(photoBubble), 'bubble does not show the raw B/L');
    assert.equal(await page.locator('.doc-chip').count(), 0, 'chip is removed after a successful send');
    assert((await page.locator('.chat-turn.assistant').count()) >= 1, 'a lookup answer arrives');
    check(`document photo only: chip, no auto send, one user turn ${width}`);
    // (2) 사진 + 글
    await attachPng(); await page.locator('.doc-chip').waitFor();
    await input(page).fill('이 서류 확인해 줘');
    sentFrom = await userTurns();
    await sendBtn.click();
    await page.waitForFunction(n => document.querySelectorAll('.chat-turn.user').length === n, sentFrom + 1, {timeout: 15000});
    await settle();
    assert.equal(await userTurns(), sentFrom + 1, 'photo + text: exactly one user turn');
    const bothBubble = await page.locator('.chat-turn.user').last().textContent();
    assert(bothBubble.includes('이 서류 확인해 줘') && bothBubble.includes('notice.png'), 'bubble shows the typed text and the file name');
    check(`document photo + text: one user turn ${width}`);
    // (3) 글만: 전과 같다
    sentFrom = await userTurns();
    await input(page).fill('중국에서 부산 들어오는 배 보여줘');
    assert(await sendBtn.isEnabled(), 'send is enabled for text only');
    await sendBtn.click();
    await page.waitForFunction(n => document.querySelectorAll('.chat-turn.user').length === n, sentFrom + 1, {timeout: 15000});
    await settle();
    assert.equal(await userTurns(), sentFrom + 1, 'text only: exactly one user turn');
    check(`text only send: one user turn ${width}`);

    // 이력: 필터, 저장된 판정 재생, 다시 조회해도 재생 스냅샷 조건 그대로
    // 사이드바 개편: 좁은 화면은 메뉴 서랍을 열고, "화물" 묶음이 접혀 있으면 펼친 뒤 누른다
    if (await page.getByRole('button', {name: '메뉴 열기'}).isVisible()) await page.getByRole('button', {name: '메뉴 열기'}).click();
    const cargoGroup = page.locator('.sb-group-head'); if (await cargoGroup.getAttribute('aria-expanded') === 'false') await cargoGroup.click();
    await page.getByRole('link', {name: '조회 이력'}).first().click(); await page.locator('.hist-list > li').first().waitFor();
    await page.getByLabel('B/L 번호 검색').fill('ZZZZ'); assert.equal(await page.locator('.hist-list > li').count(), 0);
    await page.getByRole('button', {name: '조건 초기화'}).click(); await page.getByLabel('상태별로 거르기').selectOption('failed');
    await page.getByRole('button', {name: /저장된 판정 열기/}).click(); await page.locator('[data-status="failed"]').waitFor();
    await page.getByText('저장된 이력', {exact: true}).waitFor({state: 'attached'});
    if (await handle.isVisible() && (await handle.getAttribute('aria-expanded')) === 'false') await handle.click();
    assert(await page.getByText('저장된 이력', {exact: true}).isVisible(), 'replay chip is shown');
    await page.getByRole('button', {name: '다시 조회하기', exact: true}).click(); await page.locator('[data-testid="result"][aria-busy="false"]').waitFor();
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

      // 예시는 채우기만 하고 보내지 않는다 (대화가 빈 첫 화면)
      await page.locator('.chat-examples button').first().click();
      assert((await input(page).inputValue()).length > 0, 'example fills the composer'); assert.equal(await turns(page), 0, 'example does not send');
      await input(page).fill('');
      check(`live: example fills only ${width}`);

      await page.goto(`${live}/metrics`); await page.getByText('운영자만 볼 수 있는 화면이에요.').waitFor();
      check(`live: direct /metrics is blocked for a normal user ${width}`);

      await page.goto(live); await input(page).waitFor();
      await input(page).fill('STREAM 테스트'); await input(page).press('Enter');
      await page.locator('.pending-steps li').nth(2).waitFor();
      const steps = await page.locator('.pending-steps li').evaluateAll(els => els.map(e => `${e.className}:${e.textContent.replace(/\s*(완료|진행 중)$/, '')}`));
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


      // 선박 검색 답은 표로 (3칸 머리글, 줄 나눔, 가로 넘침 없음), "나머지 N척 전체 보기"가 표를 연다, 직전 기항지 40곳은 접어 둔다
      await input(page).fill('VESSELS 일본에서 오는 배'); await input(page).press('Enter');
      await page.locator('.cvt-list').waitFor();
      assert.equal(await page.locator('.cvt-list li').count(), 5);
      assert.equal(await page.locator('.cvt-list th, .cvt-list thead').count(), 0, 'no visible column headers');
      assert.equal(await page.locator('.cvt-lead').textContent(), '일본에서 1주 안에 부산 오는 수입 화물선 43척이에요.');
      assert.equal(await page.locator('.cvt').getByText('· TEST VESSEL').count(), 0, 'raw dot lines are hidden when the table is drawn');
      assert.match(await page.locator('.cvt-eta').first().innerText(), /10\/7 \([일월화수목금토]\) \d\d:\d\d$/);
      assert(await page.evaluate(() => [...document.querySelectorAll('.cvt-eta')].every(e => e.getBoundingClientRect().height < 30)), 'time never wraps');
      assert.equal(await page.locator('.cvt-note').textContent(), '해수부 입항 신고의 직전 기항지 기준이에요.');
      await overflow(page, width);
      assert(await page.evaluate(() => { const w = document.querySelector('.cvt-list'); return w.scrollWidth <= w.clientWidth + 1; }), 'vessel table does not overflow its bubble');
      await page.screenshot({path: `${SHOTS77}/chat-vessel-table-${width}.png`});
      await page.locator('.vessel-results').waitFor();
      // 휴대폰: 입력창에 포커스가 있으면 시트가 접혀 있어 손잡이로 편다
      const sheet = page.locator('.sheet-handle');
      if (await sheet.isVisible() && (await sheet.getAttribute('aria-expanded')) === 'false') await sheet.click();
      const hdr = page.locator('.vl-head');
      assert.equal(await hdr.locator('.vl-meta').textContent(), '43척 · 7일 · 모든 시각 한국 시간');
      assert.equal(await page.locator('.vl-ports summary').textContent(), '직전 기항지 40곳항구 보기');
      assert.equal(await page.locator('.vl-ports .vl-chips').isVisible(), false, 'ports are collapsed at first');
      await page.locator('.vl-ports summary').click();
      assert.equal(await page.locator('.vl-ports .vl-chips li').count(), 40);
      await page.screenshot({path: `${SHOTS77}/vessel-list-header-${width}.png`});
      await overflow(page, width);
      // 휴대폰: 시트를 접어 둔 뒤 누르면 표가 다시 펼쳐진다
      if (await sheet.isVisible() && (await sheet.getAttribute('aria-expanded')) === 'true') await sheet.click();
      await page.locator('.cvt-more').click();
      await page.locator('.vessel-results').waitFor();
      if (await sheet.isVisible()) assert.equal(await sheet.getAttribute('aria-expanded'), 'true', 'more-button reopens the sheet');
      assert.equal(await page.locator('.cvt-more').textContent(), '나머지 38척 전체 보기');
      check(`live: vessel answer renders table, 3 headers, no overflow, more-button, port disclosure ${width}`);

      await input(page).fill('BROKEN 질문'); await input(page).press('Enter');
      await page.locator('.chat-turn.assistant', {hasText: '답을 만드는 중 문제가 생겼습니다.'}).waitFor();
      assert.equal(await input(page).inputValue(), 'BROKEN 질문', 'input restored after an error');
      check(`live: stream error is shown and input restored ${width}`);

      await page.goto(`${live}/history`); await page.getByText('이력을 불러올 수 없어요.').waitFor();
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
