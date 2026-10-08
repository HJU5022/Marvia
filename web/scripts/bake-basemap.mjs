/** 지도 바탕을 정적 래스터 타일로 미리 구워 두는 스크립트. 다시 굽기: `node scripts/bake-basemap.mjs`
 *
 * 왜 하나
 * - WebGL이 없는 컴퓨터(발표장 PC 등)에서는 OpenFreeMap 벡터 지도를 그릴 수 없다. 그래서 같은 지도를 미리 그림 파일(XYZ 타일)로 구워
 *   public/basemap/{z}/{x}/{y}.webp 로 같이 배포한다. lib/basemap.ts 의 2단계(WebGL 없음/벡터 실패)가 이 타일을 쓴다.
 * - 같은 모양이어야 하므로 lib/basemap.ts 의 tune()과 같은 손질(땅·바다 색은 globals.css 의 --land/--sea, 도로·철도·건물·공항·시군구 경계·마을 이름 숨김,
 *   한국어 이름 우선)을 이 스크립트 안에 똑같이 다시 적었다(.ts 를 .mjs 가 직접 불러올 수 없어서). 한쪽을 고치면 다른 쪽도 고칠 것.
 *
 * 어떻게 굽나
 * - Playwright 로 진짜 Chrome(WebGL 켬)을 열고 maplibre-gl 로 지도를 그린 뒤 256px 타일로 자른다.
 * - 타일 경계에서 이름표가 잘리지 않도록 구역보다 사방 1타일 큰 화면으로 한 번에 그린 뒤 가운데만 자른다.
 * - 바다만 있는 타일(전부 바다 색)은 파일을 만들지 않는다. 지도 컨테이너 배경이 바다 색이라 비어 있어도 똑같이 보인다.
 *   단 확대 8 타일은 아래 레이어(확대 7 늘린 것)가 비쳐 보이지 않게 바다 타일도 그대로 쓴다.
 * - 타일 목록은 meta.json 의 tiles 에 넣어 둔다. 브라우저가 없는 타일을 요청해 404 를 쌓지 않도록 목록에 있는 것만 요청한다.
 * - 이미지 인코딩은 Next 가 이미 깔아 둔 sharp(WebP)를 쓴다. 새로 설치하는 것은 없다.
 * - 좌표계는 일반 XYZ(웹 메르카토르, 256px, 1배율). maplibre 확대 z-1 이 Leaflet 확대 z 와 같은 크기다(maplibre 타일이 512px 이라서). */
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
import sharp from 'sharp';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outDir = path.join(root, 'public', 'basemap');
const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'; // lib/basemap.ts 의 STYLE_URL 과 같다
const ATTRIBUTION = '© OpenStreetMap · OpenFreeMap';
// 손실 압축(q78)은 바다 색을 1~2단계 어긋나게 해서 타일 사이에 옅은 사각형 이음선이 보였다. 바다 픽셀이 sea.webp·배경색과 정확히 같도록 무손실로 굽는다.
// 지도가 단색 위주라 무손실이어도 용량이 작다
const WEBP = {lossless: true, effort: 6};
// 구울 구역. 확대 3~7 은 전체 구역, 확대 8 은 DETAIL 구역만 (용량 때문, 승인된 범위)
const REGION = {west: 100, east: 155, south: 10, north: 50};
// 확대 8: 한국 + 일본 서부 + 중국 동해안
const DETAIL = {west: 118, east: 136, south: 28, north: 40};
const PLAN = [3, 4, 5, 6, 7].map((z) => ({z, box: REGION, keepSea: false})).concat([{z: 8, box: DETAIL, keepSea: true}]);

// globals.css 의 --land / --sea 를 그대로 읽는다 (lib/basemap.ts 가 getComputedStyle 로 읽는 값과 같다)
const css = fs.readFileSync(path.join(root, 'app', 'globals.css'), 'utf8');
const token = (n) => css.match(new RegExp(`--${n}:\\s*(#[0-9a-fA-F]{3,8})`))?.[1];
const LAND = token('land'), SEA = token('sea');
if (!LAND || !SEA) throw new Error('globals.css 에서 --land/--sea 를 못 읽음');
const seaRgb = [1, 3, 5].map((i) => parseInt(SEA.slice(i, i + 2), 16));

// 웹 메르카토르 타일 번호 <-> 경위도
const xf = (lon, z) => ((lon + 180) / 360) * 2 ** z;
const yf = (lat, z) => ((1 - Math.log(Math.tan((lat * Math.PI) / 180) + 1 / Math.cos((lat * Math.PI) / 180)) / Math.PI) / 2) * 2 ** z;
const lonOf = (x, z) => (x / 2 ** z) * 360 - 180;
const latOf = (y, z) => (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / 2 ** z))) * 180) / Math.PI;

const mlDir = path.join(root, 'node_modules', 'maplibre-gl', 'dist');
const HTML = `<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="http://bake.local/ml.css"></head><body style="margin:0"><div id="m" style="position:absolute;left:0;top:0"></div></body></html>`;

const browser = await chromium.launch({channel: 'chrome', headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-webgl']});
const page = await browser.newPage({viewport: {width: 1000, height: 800}});
// maplibre 본체·워커·css 는 node_modules 에서 가짜 주소로 내려 준다 (새 설치 없이, 같은 출처로 워커 로딩)
const files = {'/ml.mjs': ['maplibre-gl.mjs', 'text/javascript'], '/ml-shared.mjs': ['maplibre-gl-shared.mjs', 'text/javascript'], '/ml-worker.mjs': ['maplibre-gl-worker.mjs', 'text/javascript'], '/ml.css': ['maplibre-gl.css', 'text/css']};
await page.route('http://bake.local/**', (r) => {
  const p = new URL(r.request().url()).pathname;
  if (p === '/') return r.fulfill({contentType: 'text/html', body: HTML});
  const f = files[p];
  if (!f) return r.fulfill({status: 404, body: ''});
  r.fulfill({contentType: f[1], body: fs.readFileSync(path.join(mlDir, f[0]))});
});
await page.goto('http://bake.local/');
page.on('pageerror', (e) => console.log('pageerror', e.message));

// maplibre-gl.mjs 가 공유 조각을 상대 경로로 불러오므로 원래 이름으로도 내려 준다
files['/maplibre-gl-shared.mjs'] = files['/ml-shared.mjs'];
files['/maplibre-gl-worker.mjs'] = files['/ml-worker.mjs'];

await page.evaluate(async () => {
  const ml = await import('http://bake.local/ml.mjs');
  ml.setWorkerUrl('http://bake.local/maplibre-gl-worker.mjs');
  window.ML = ml;
});
const webgl = await page.evaluate(() => !!document.createElement('canvas').getContext('webgl2'));
if (!webgl) throw new Error('이 Chrome 에서 WebGL 을 못 켬. 굽기를 중단함');

/** 한 구역을 큰 화면으로 그려 PNG(base64)로 돌려준다. tune 부분은 lib/basemap.ts 의 tune()과 같은 내용이다 */
async function renderBlock(z, x0, y0, nx, ny) {
  const W = (nx + 2) * 256, H = (ny + 2) * 256;
  const size = 256 * 2 ** z;
  const lng = ((x0 + nx / 2) * 256) / size * 360 - 180;
  const lat = (Math.atan(Math.sinh(Math.PI * (1 - (2 * (y0 + ny / 2) * 256) / size))) * 180) / Math.PI;
  return page.evaluate(async ({STYLE_URL, LAND, SEA, z, W, H, lng, lat}) => {
    const el = document.getElementById('m');
    el.innerHTML = ''; el.style.width = W + 'px'; el.style.height = H + 'px';
    const map = new window.ML.Map({container: el, style: STYLE_URL, center: [lng, lat], zoom: z - 1, pixelRatio: 1, interactive: false, attributionControl: false, renderWorldCopies: false, fadeDuration: 0, canvasContextAttributes: {preserveDrawingBuffer: true}});
    const paint = (id, prop, v) => { try { if (v && map.getLayer(id)) map.setPaintProperty(id, prop, v); } catch {} };
    await new Promise((res, rej) => { map.once('style.load', res); map.once('error', (e) => { if (!map.isStyleLoaded()) rej(e.error); }); });
    // ---- lib/basemap.ts tune() 과 같은 손질 시작 ----
    paint('background', 'background-color', LAND);
    paint('water', 'fill-color', SEA);
    const QUIET = /^(highway|railway|aeroway|building|bridge|tunnel|landuse|boundary_3|airport|label_village|label_other|waterway)/;
    for (const l of map.getStyle().layers) { if (QUIET.test(l.id)) { try { map.setLayoutProperty(l.id, 'visibility', 'none'); } catch {} } }
    for (const l of map.getStyle().layers) {
      if (l.type !== 'symbol') continue;
      const tf = l.layout?.['text-field'];
      if (!tf || /"ref"|"iata"/.test(JSON.stringify(tf))) continue;
      try { map.setLayoutProperty(l.id, 'text-field', ['coalesce', ['get', 'name:ko'], ['get', 'name']]); } catch {}
    }
    // ---- 손질 끝 ----
    await new Promise((res) => { const go = () => map.once('idle', () => setTimeout(() => (map.loaded() ? res() : go()), 400)); go(); });
    const png = map.getCanvas().toDataURL('image/png').split(',')[1];
    map.remove();
    return png;
  }, {STYLE_URL, LAND, SEA, z, W, H, lng, lat});
}

fs.rmSync(outDir, {recursive: true, force: true});
fs.mkdirSync(outDir, {recursive: true});
let seaBuf = null; // 바다만인 타일 하나를 다른 타일과 똑같이 인코딩한 것 → sea.webp
const tiles = [], perZoom = {}, skippedSea = {}, bytesPerZoom = {};
for (const {z, box, keepSea} of PLAN) {
  const n = 2 ** z;
  const x0 = Math.max(0, Math.floor(xf(box.west, z))), x1 = Math.min(n - 1, Math.floor(xf(box.east, z) - 1e-9));
  const y0 = Math.max(0, Math.floor(yf(box.north, z))), y1 = Math.min(n - 1, Math.floor(yf(box.south, z) - 1e-9));
  const nx = x1 - x0 + 1, ny = y1 - y0 + 1;
  perZoom[z] = 0; skippedSea[z] = 0; bytesPerZoom[z] = 0;
  // 한 번에 그리는 크기를 12x12 타일로 제한하고 나눠 그린다 (WebGL 화면 크기 한계). 조각마다 사방 1타일 여유를 둔다
  const CH = 12;
  for (let cy = y0; cy <= y1; cy += CH) for (let cx = x0; cx <= x1; cx += CH) {
    const cnx = Math.min(CH, x1 - cx + 1), cny = Math.min(CH, y1 - cy + 1);
    console.log(`z${z}: 조각 (${cx},${cy}) ${cnx}x${cny} 그리는 중`);
    const full = Buffer.from(await renderBlock(z, cx, cy, cnx, cny), 'base64');
    for (let ty = 0; ty < cny; ty++) for (let tx = 0; tx < cnx; tx++) {
      const crop = sharp(full).extract({left: (tx + 1) * 256, top: (ty + 1) * 256, width: 256, height: 256}).removeAlpha();
      const raw = await crop.clone().raw().toBuffer();
      let sea = true;
      for (let i = 0; i < raw.length; i += 3) { if (Math.abs(raw[i] - seaRgb[0]) > 3 || Math.abs(raw[i + 1] - seaRgb[1]) > 3 || Math.abs(raw[i + 2] - seaRgb[2]) > 3) { sea = false; break; } }
      if (sea && !keepSea) {
        skippedSea[z]++;
        if (!seaBuf) seaBuf = await crop.webp(WEBP).toBuffer();
        continue;
      }
      const buf = await crop.webp(WEBP).toBuffer();
      const dir = path.join(outDir, String(z), String(cx + tx));
      fs.mkdirSync(dir, {recursive: true});
      fs.writeFileSync(path.join(dir, `${cy + ty}.webp`), buf);
      tiles.push(`${z}/${cx + tx}/${cy + ty}`); perZoom[z]++; bytesPerZoom[z] += buf.length;
    }
  }
  console.log(`z${z}: 저장 ${perZoom[z]}장, 바다만이라 건너뜀 ${skippedSea[z]}장, ${(bytesPerZoom[z] / 1024).toFixed(0)}KB`);
}
await browser.close();

// 건너뛴 바다 타일 자리에는 브라우저가 이 sea.webp 한 장을 대신 쓴다. 바다 픽셀이 전부 같은 방식으로 인코딩되어 손실 압축 때문에 생기는 색 차이(이음선)가 없다.
// 칸 배경색도 이 이미지를 다시 읽은 색으로 맞춘다 (meta.seaEncoded)
if (!seaBuf) throw new Error('바다만인 타일이 없어 sea.webp 를 못 만듦');
fs.writeFileSync(path.join(outDir, 'sea.webp'), seaBuf);
const sm = await sharp(seaBuf).removeAlpha().stats();
const seaEncoded = '#' + sm.channels.map((c) => Math.round(c.mean).toString(16).padStart(2, '0')).join('');
const totalBytes = Object.values(bytesPerZoom).reduce((a, b) => a + b, 0) + seaBuf.length;
const meta = {
  baked: new Date().toISOString().slice(0, 10), style: STYLE_URL, attribution: ATTRIBUTION,
  tileSize: 256, format: 'webp', lossless: true, land: LAND, sea: SEA, seaEncoded, seaTile: 'sea.webp',
  bounds: [[REGION.south, REGION.west], [REGION.north, REGION.east]], // Leaflet 순서 [위도, 경도]
  detailBounds: [[DETAIL.south, DETAIL.west], [DETAIL.north, DETAIL.east]],
  minZoom: 3, maxNativeZoom: 7, detailZoom: 8,
  tileCount: tiles.length, totalBytes, perZoom, skippedSea, bytesPerZoom,
  tiles, // "z/x/y" 목록. 여기 없는 타일(바다만)은 요청하지 않는다
};
fs.writeFileSync(path.join(outDir, 'meta.json'), JSON.stringify(meta));
console.log(`끝: 타일 ${tiles.length}장, 합계 ${(totalBytes / 1024 / 1024).toFixed(2)}MB`);
