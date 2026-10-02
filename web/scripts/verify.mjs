/** End-to-end acceptance: npm run dev must be running at MARVIA_TEST_URL (default :3100).
 * Uses installed Chrome by default; PLAYWRIGHT_CHANNEL can override the browser channel.
 * All off-origin HTTP is blocked and recorded: the app must run on local assets only.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {chromium} from 'playwright';
import AxeBuilder from '@axe-core/playwright';
const base=process.env.MARVIA_TEST_URL??'http://127.0.0.1:3100';
const browser=await chromium.launch({channel:process.env.PLAYWRIGHT_CHANNEL??'chrome',headless:true});
const failures=[],pageErrors=[],external=[],checks=[];
const interactionsOnly=process.argv.includes('--interactions');
const check=(name,detail={})=>{checks.push({name,...detail});console.log('PASS',name);};
async function ready(page){await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(150);}
async function cargo(page,id){await page.goto(`${base}/?fixture=${id}`);await page.locator('[data-testid="result"]').waitFor();await ready(page);}
async function overflow(page,width){const w=await page.evaluate(()=>document.documentElement.scrollWidth);assert(w<=width,`overflow ${w}>${width}`);}
async function audit(page,name){const results=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();for(const v of results.violations)failures.push({page:name,id:v.id,impact:v.impact,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))});}
try {
 for(const width of [1440,375]){
  const context=await browser.newContext({viewport:{width,height:1000},deviceScaleFactor:1,reducedMotion:'reduce'});
  await context.route('**/*',route=>{const url=new URL(route.request().url());if(url.protocol.startsWith('http')&&url.origin!==new URL(base).origin){external.push(url.origin);return route.abort();}return route.continue();});
  const page=await context.newPage();page.on('pageerror',e=>pageErrors.push(e.message));
  for(const [i,id] of (interactionsOnly?[]:['ok','partial','insufficient','failed','unsupported','watch','act']).entries()){
   await cargo(page,id);assert.equal(await page.locator('[data-testid="result"]').getAttribute('data-status'),['watch','act'].includes(id)?'ok':id);
   if(id==='insufficient')assert.equal(await page.locator('.verdict-hero').count(),0);
   if(['partial','failed','unsupported'].includes(id))assert.equal(await page.locator('.verdict-hero').count(),0);
   if(id==='partial')assert.equal(await page.locator('.map-stale').count(),1);
   if(id==='unsupported')assert.match(await page.locator('.map-section h2').innerText(),/기준 지도/);
   if(id!=='insufficient')await page.locator('.leaflet-overlay-pane svg').waitFor();
   await overflow(page,width);await audit(page,`${id}-${width}`);
   await page.screenshot({path:`screenshots/${String(i+1).padStart(2,'0')}-${id}-${width}.png`,fullPage:true});check(`${id} ${width}px`);
  }
  for(const [i,route] of (interactionsOnly?[]:['history','metrics','settings','about']).entries()){
   await page.goto(`${base}/${route}`);if(route==='history')await page.locator('tbody tr').first().waitFor();await ready(page);await overflow(page,width);await audit(page,`${route}-${width}`);
   await page.screenshot({path:`screenshots/${String(i+8).padStart(2,'0')}-${route}-${width}.png`,fullPage:true});check(`${route} ${width}px`);
  }
  await cargo(page,'ok');
  await page.locator('#bl').fill('!!');await page.getByRole('button',{name:'화물 조회',exact:true}).click();assert(await page.locator('#bl-error').isVisible());check(`inline B/L validation ${width}`);
  await page.locator('#bl').fill(' mrv demo1101 ');await page.evaluate(()=>{window.__stages=[];window.__stageObserver=new MutationObserver(()=>{const t=document.querySelector('.progress-steps .current')?.textContent;if(t)window.__stages.push(t);});window.__stageObserver.observe(document.body,{subtree:true,childList:true,attributes:true});});await page.getByRole('button',{name:'화물 조회',exact:true}).click();await page.getByRole('button',{name:'화물 조회',exact:true}).waitFor();const stages=await page.evaluate(()=>{window.__stageObserver.disconnect();return window.__stages;});for(const stage of ['식별','위치','판정'])assert(stages.some(s=>s.includes(stage)),`missing stage ${stage}`);assert.equal(await page.locator('#bl').inputValue(),'MRVDEMO1101');check(`normalization + three stages ${width}`);
  await page.locator('#sale-date').fill('2026-10-01');await page.getByRole('button',{name:'화물 조회',exact:true}).click();await page.locator('.request-error').waitFor();assert.match(await page.locator('.request-error').innerText(),/저장된 예시/);check(`date mismatch rejected ${width}`);
  await cargo(page,'insufficient');await page.getByRole('button',{name:'확인하고 판정 진행'}).click();assert(await page.locator('.candidate-section [role=alert]').isVisible());await page.getByRole('radio').first().check();await page.getByRole('button',{name:'확인하고 판정 진행'}).click();await page.locator('[data-status="ok"]').waitFor();check(`candidate validation + resolution ${width}`);
  await page.locator('#question').fill('판매 일정을 확인해 주세요.');await page.getByRole('button',{name:'질문 보내기'}).click();await page.locator('.agent-message').waitFor();assert.match(await page.locator('.agent-message').innerText(),/저장.*재생/);await page.locator('.agent-message summary').click();assert((await page.locator('.chat-source').count())>0);check(`follow-up with returned evidence ${width}`);
  await cargo(page,'partial');await page.getByRole('button',{name:'해수부 근거만 보기'}).click();assert(await page.locator('.filter-notice').isVisible());assert.equal(await page.locator('.evidence-source').filter({hasNotText:'해양수산부'}).count(),0);await page.getByRole('button',{name:'전체 보기'}).click();await page.locator('.evidence-item summary').first().click();assert(await page.locator('.evidence-item pre').first().isVisible());check(`MOF filter + raw evidence ${width}`);
  await page.getByRole('link',{name:/조회 이력/}).first().click();await page.locator('tbody tr').first().waitFor();await page.getByLabel('B/L 뒤 네 자리 검색').fill('ZZZZ');assert.equal(await page.locator('tbody tr').count(),0);await page.getByRole('button',{name:'필터 초기화'}).click();await page.getByLabel('상태 필터').selectOption('failed');await page.getByRole('button',{name:/저장된 판정 열기/}).click();await page.locator('[data-status="failed"]').waitFor();assert(await page.getByText('이력 재생',{exact:true}).isVisible());await page.getByRole('button',{name:'다시 조회',exact:true}).click();await page.getByRole('button',{name:'화물 조회',exact:true}).waitFor();assert.equal(await page.locator('[data-testid="result"]').getAttribute('data-status'),'failed');check(`history filter + replay + retry isolation ${width}`);
  await context.close();
 }
 assert.deepEqual(pageErrors,[],'Browser errors');assert.deepEqual(external,[],'Unexpected external HTTP');
 fs.writeFileSync('screenshots/verification.json',JSON.stringify({checks,accessibilityViolations:failures,pageErrors,externalRequests:external},null,2));
 assert.equal(failures.length,0,'Accessibility violations: see screenshots/verification.json');
 console.log(`PASS: ${checks.length} checks; zero page errors and external HTTP requests. ${interactionsOnly?'Interaction-only run; accessibility not checked.':'Zero axe WCAG A/AA violations.'}`);
}finally{fs.writeFileSync('screenshots/verification.json',JSON.stringify({checks,accessibilityViolations:failures,pageErrors,externalRequests:external},null,2));await browser.close();}
