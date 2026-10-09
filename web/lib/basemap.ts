/** 지도 바탕(OpenFreeMap 세계 지도)을 Leaflet 지도 밑에 깔고, 안 되면 레포의 해안선으로 되돌리는 공용 도우미.
 *
 * 왜 이렇게 했나
 * - 직접 그린 Natural Earth 해안선은 바다·해협 이름과 나라 경계가 없어 어디쯤인지 읽기 어려웠다. 키가 필요 없는 OpenFreeMap 벡터 타일을
 *   MapLibre로 그려 Leaflet 레이어로 끼운다(@maplibre/maplibre-gl-leaflet). 배·부산항·경로·클러스터·말풍선은 전부 지금처럼 Leaflet 것이다.
 * - 데모가 빈 지도로 멈추면 안 된다. WebGL이 없거나, 스타일이 8초 안에 안 오거나, 스타일이 온 뒤 8초 안에 타일이 한 장도 안 오거나, 스타일 불러오다 오류가 나면 바탕을 걷어 내고
 *   예전 해안선(lib/fixtures/geography.json)과 손으로 쓴 이름표를 그대로 보여 준다. 오프라인 시연도 같은 길이다.
 * - 4개 지도(MapPanel, ChatMiniMap, VesselMap, WatchMap)가 한 곳을 쓰므로, 지도가 사라질 때 dispose()를 부르면 WebGL 문맥도 함께 풀린다.
 * - 브라우저에서만 불러온다(동적 import). 서버 렌더링 때는 이 파일이 실행되지 않는다.
 * 외부로 나가는 주소는 tiles.openfreemap.org 하나뿐이다(스타일, 타일, 글꼴, 아이콘 모두 같은 호스트). */
import type {GeoJsonObject} from 'geojson';
import type {Map as LeafletMap} from 'leaflet';
import type {Map as GLMap} from 'maplibre-gl';
import {getGeography} from '@/lib/api';

/** 차분한 밝은 스타일(positron). 바다·땅 색은 불러온 뒤 우리 토큰으로 바꾼다 */
const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron';
/** 스타일 파일이 이 시간 안에 안 오면 예전 해안선으로 되돌린다 (스타일이 안 오면 지도를 그릴 수 없다) */
const STYLE_TIMEOUT_MS = 8000;
/** 스타일이 온 뒤 이 시간 안에 타일이 한 장도 안 오면 되돌린다. 타일이 한 장이라도 그려지면 그 뒤로는 절대 되돌리지 않는다 */
const TILE_TIMEOUT_MS = 8000;
/** 미리 구워 둔 정적 타일(2단계)이 있는 곳과 안내 파일. 만드는 법은 scripts/bake-basemap.mjs */
const BAKED_DIR = '/basemap';
/** 정적 타일 안내 파일이나 첫 타일이 이 시간 안에 안 오면 3단계(예전 해안선)로 간다 */
const STATIC_TIMEOUT_MS = 8000;
/** OpenStreetMap 데이터 사용 조건이 요구하는 저작자 표시. 작게 한 줄로 */
const ATTRIBUTION = '© OpenStreetMap · OpenFreeMap';

/** 어댑터 내부 메서드 중 우리가 바꾸는 것들의 모양(공개 타입에는 없다) */
interface GuardedLayer {
  _map: LeafletMap | null;
  _glMap: (GLMap & {_actualCanvas: HTMLCanvasElement}) | null;
  _resizeContainer(): void;
  _zoomEnd(): void;
  _transitionEnd(this: GuardedLayer): void;
}

export interface Basemap {
  /** loading: 벡터 지도를 기다리는 중, basemap: 벡터 세계 지도 사용 중, static: 미리 구운 그림 타일 사용 중(WebGL 없음), fallback: 예전 해안선으로 되돌림 */
  readonly mode: 'loading' | 'basemap' | 'static' | 'fallback';
  /** 칸 크기가 바뀐 뒤 부른다. Leaflet 쪽 invalidateSize와 함께 MapLibre 캔버스도 새 크기에 맞춘다 */
  resize(): void;
  /** 지도를 지우기 전에 부른다. 대기 시간 타이머와 WebGL 레이어를 정리한다 */
  dispose(): void;
}

/** 브라우저가 WebGL을 켤 수 있는지. 못 켜면 MapLibre 만들기에서 오류가 나므로 미리 본다 */
function hasWebGL() {
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl2') || c.getContext('webgl'));
  } catch { return false; }
}

/** 예전 방식의 바탕: 레포에 든 Natural Earth 해안선. 마커·경로보다 항상 아래에 깔도록 맨 뒤로 보낸다
 * (바탕이 늦게 그려지는 되돌림 경로에서도 이미 올라간 선을 덮지 않게) */
export function drawLocalGeography(L: typeof import('leaflet'), map: LeafletMap) {
  const css = getComputedStyle(document.documentElement);
  const c = (n: string) => css.getPropertyValue(n).trim();
  return L.geoJSON(getGeography() as GeoJsonObject, {style: {color: c('--coast'), weight: 1, fillColor: c('--land'), fillOpacity: 1}, interactive: false}).addTo(map).bringToBack();
}

/** 불러온 스타일을 우리 팔레트와 한국어 이름표로 맞춘다. 레이어가 없으면(스타일이 바뀌면) 그 항목만 건너뛴다 */
function tune(gl: GLMap) {
  const css = getComputedStyle(document.documentElement);
  const c = (n: string) => css.getPropertyValue(n).trim();
  const paint = (id: string, prop: 'background-color' | 'fill-color', v: string) => { try { if (v && gl.getLayer(id)) gl.setPaintProperty(id, prop, v); } catch { /* 레이어가 없으면 건너뜀 */ } };
  paint('background', 'background-color', c('--land'));
  paint('water', 'fill-color', c('--sea'));
  // 조용한 배경: 도로, 철도, 건물, 공항, 시군구 경계, 마을 이름은 배 위치를 읽는 데 방해라서 숨긴다. 바다·나라·도시 이름과 나라 경계만 남긴다
  const QUIET = /^(highway|railway|aeroway|building|bridge|tunnel|landuse|boundary_3|airport|label_village|label_other|waterway)/;
  for (const l of gl.getStyle().layers) {
    if (QUIET.test(l.id)) { try { gl.setLayoutProperty(l.id, 'visibility', 'none'); } catch { /* 건너뜀 */ } }
  }
  // 이름표는 한국어 이름이 있으면 그것을, 없으면 원래 이름을 쓴다. 도로 번호판(ref)과 공항 코드는 이름이 아니라서 건드리지 않는다
  for (const l of gl.getStyle().layers) {
    if (l.type !== 'symbol') continue;
    const tf = l.layout?.['text-field'];
    if (!tf || /"ref"|"iata"/.test(JSON.stringify(tf))) continue;
    try { gl.setLayoutProperty(l.id, 'text-field', ['coalesce', ['get', 'name:ko'], ['get', 'name']]); } catch { /* 건너뜀 */ }
  }
}

/** 구워 둔 타일 안내 파일(meta.json)의 모양 중 쓰는 것만 */
interface BakedMeta {
  attribution: string; sea: string; seaEncoded?: string; seaTile?: string;
  bounds: [[number, number], [number, number]]; detailBounds: [[number, number], [number, number]];
  minZoom: number; maxNativeZoom: number; detailZoom: number; tiles: string[];
}

/** Leaflet 지도(중심과 확대가 이미 정해진 것) 밑에 세계 지도를 깐다. 3단계로 내려간다:
 * 1) WebGL이 되면 OpenFreeMap 벡터 지도, 2) 안 되거나 실패하면 미리 구운 그림 타일(public/basemap), 3) 그것도 안 되면 예전 해안선. 3단계에서 onFallback이 불린다.
 * onFallback 안에서 drawLocalGeography와 손으로 쓴 이름표를 올린다. 이름표는 되돌림 때만 그려야 세계 지도와 겹치지 않는다 */
export function addBasemap(L: typeof import('leaflet'), map: LeafletMap, onFallback: () => void): Basemap {
  let disposed = false;
  let mode: Basemap['mode'] = 'loading';
  let timer: ReturnType<typeof setTimeout> | undefined;
  let layer: ReturnType<typeof import('@maplibre/maplibre-gl-leaflet').maplibreGL> | null = null;
  let observer: ResizeObserver | undefined;
  let staticTimer: ReturnType<typeof setTimeout> | undefined;
  let staticLayers: import('leaflet').TileLayer[] = [];
  let restore: (() => void) | null = null;
  let applyMin: (() => void) | null /* 2단계의 resize 구독 해제 */ = null;

  /** 3단계: 예전 해안선과 손으로 쓴 이름표. 2단계에서 바꾼 지도 제한(확대 범위, 이동 범위, 바다색 배경)도 원래대로 돌린다 */
  const toFallback = () => {
    if (disposed || mode === 'fallback') return;
    mode = 'fallback'; clearTimeout(timer); clearTimeout(staticTimer); observer?.disconnect();
    for (const t of staticLayers) { try { map.removeLayer(t); } catch { /* 이미 지워짐 */ } }
    staticLayers = []; applyMin?.(); applyMin = null; restore?.(); restore = null;
    // 오류 이벤트 안에서 바로 걷으면 MapLibre가 자기 이벤트 도중 지워지므로 한 박자 뒤에 걷는다
    const l = layer; layer = null;
    if (l) setTimeout(() => { try { map.removeLayer(l); } catch { /* 이미 지워짐 */ } }, 0);
    map.attributionControl?.addAttribution('Natural Earth (public domain)');
    onFallback();
  };

  /** 2단계: 미리 구운 타일. 땅 타일만 파일이 있고 바다만인 곳은 파일이 없어서, 안내 파일의 목록에 있는 타일만 요청하고
   * 나머지는 지도 칸 배경(바다색)이 보이게 둔다. 확대는 3~8(작은 칸에서는 구운 구역이 칸을 채우는 확대 이상), 이동은 구운 구역 안으로 제한한다(이 단계에서만).
   * 확대 7까지는 전체 구역, 8은 한국·일본 서부·중국 동해안만이라 레이어를 둘로 나눈다(8에서 부산 밖은 7을 늘려 보여 준다). 이름표가 타일에 이미 들어 있다 */
  const toStatic = async () => {
    if (disposed || mode === 'static' || mode === 'fallback') return;
    mode = 'static'; clearTimeout(timer); observer?.disconnect(); observer = undefined;
    const l = layer; layer = null;
    if (l) setTimeout(() => { try { map.removeLayer(l); } catch { /* 이미 지워짐 */ } }, 0);
    // 안내 파일이 안 오면(파일 없음, 느림) 3단계
    clearTimeout(staticTimer); staticTimer = setTimeout(toFallback, STATIC_TIMEOUT_MS);
    let meta: BakedMeta;
    try {
      const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), STATIC_TIMEOUT_MS);
      const res = await fetch(`${BAKED_DIR}/meta.json`, {signal: ctl.signal}); clearTimeout(t);
      if (!res.ok) throw new Error('meta');
      meta = await res.json() as BakedMeta;
      if (!Array.isArray(meta.tiles) || !meta.tiles.length) throw new Error('meta');
    } catch { toFallback(); return; }
    if (disposed || mode !== 'static') return;
    const have = new Set(meta.tiles);
    // 건너뛴 바다 타일 자리에는 sea.webp 한 장을 쓴다(fill). 바다 픽셀이 모두 같은 방식으로 인코딩되어 손실 압축 색 차이로 생기는 이음선이 없다.
    // 확대 8(detail) 레이어는 구운 구역 밖이 비어 있어야(아래 확대 7이 비쳐야) 하므로 목록에 없으면 빈 칸으로 둔다
    const seaUrl = `${BAKED_DIR}/${meta.seaTile ?? 'sea.webp'}`;
    const make = (opts: import('leaflet').TileLayerOptions, fill: boolean) => {
      const t = L.tileLayer(`${BAKED_DIR}/{z}/{x}/{y}.webp`, {...opts, attribution: meta.attribution, errorTileUrl: ''});
      const g = t as unknown as {
        createTile(c: {x: number; y: number; z: number}, done: (e?: Error, el?: HTMLElement) => void): HTMLElement;
        getTileUrl(c: {x: number; y: number; z: number}): string;
      };
      const url = g.getTileUrl.bind(t), orig = g.createTile.bind(t);
      g.getTileUrl = (c) => have.has(`${c.z}/${c.x}/${c.y}`) ? url(c) : seaUrl;
      if (!fill) {
        g.createTile = (c, done) => {
          if (have.has(`${c.z}/${c.x}/${c.y}`)) return orig(c, done);
          const d = document.createElement('div'); setTimeout(() => done(undefined, d), 0); return d;
        };
      }
      return t;
    };
    const baseTiles = make({minZoom: meta.minZoom, maxZoom: meta.detailZoom, maxNativeZoom: meta.maxNativeZoom}, true);
    const busanTiles = make({minZoom: meta.detailZoom, maxZoom: meta.detailZoom, maxNativeZoom: meta.detailZoom}, false);
    staticLayers = [baseTiles, busanTiles];
    // 진짜 그림 타일(img)이 하나라도 오면 성공. 목록에 있는 타일이 오류로 몇 장 연속 실패하면 3단계
    let loaded = 0, failed = 0;
    for (const t of staticLayers) {
      t.on('tileload', (e) => { if ((e as unknown as {tile: Element}).tile instanceof HTMLImageElement) { loaded++; clearTimeout(staticTimer); } });
      t.on('tileerror', () => { failed++; if (!loaded && failed >= 3) toFallback(); });
    }
    // 지도 제한은 이 단계에서만. 원래 값을 저장해 3단계로 가면 되돌린다
    const el = map.getContainer(), old = {bg: el.style.background, min: map.getMinZoom(), max: map.getMaxZoom(), bounds: map.options.maxBounds, visc: map.options.maxBoundsViscosity};
    restore = () => {
      el.style.background = old.bg; map.setMinZoom(old.min); map.setMaxZoom(old.max);
      map.options.maxBoundsViscosity = old.visc; map.setMaxBounds(old.bounds as never);
    };
    el.style.background = meta.seaEncoded ?? meta.sea;
    // 타일 레이어에는 bounds를 주지 않는다(구운 구역 가장자리 타일이 잘려 이음선이 생겼다). 있는 타일만 목록으로 거른다.
    // 작은 칸에서 구운 구역 밖의 빈 바다가 보이지 않게, 최소 확대는 구운 구역이 칸을 채우는 확대(3 이상)로 맞추고 칸 크기가 바뀌면 다시 맞춘다
    const region = L.latLngBounds(meta.bounds);
    const fitMin = () => { try { map.setMinZoom(Math.min(meta.maxNativeZoom, Math.max(meta.minZoom, Math.ceil(map.getBoundsZoom(region, true))))); } catch { /* 칸 크기가 0 */ } };
    map.setMaxZoom(meta.detailZoom); fitMin(); map.on('resize', fitMin); applyMin = () => map.off('resize', fitMin);
    map.options.maxBoundsViscosity = 1; map.setMaxBounds(region);
    baseTiles.addTo(map); busanTiles.addTo(map);
  };

  /** 벡터 지도가 안 될 때 간다. 먼저 구운 타일(2단계)을 시도하고, 그것도 안 되면 toFallback이 불린다 */
  const toNext = () => { if (!disposed && mode === 'loading') void toStatic(); };

  /** 대기 시간을 건다. 탭이 숨겨진 동안(배경 탭, 다른 창)에는 브라우저가 그리기 프레임을 멈춰서 MapLibre가 타일을 요청조차 못 하므로,
   * 그때 시간이 다 돼도 되돌리지 않고 보일 때까지 기다린다. 숨겨졌다 돌아오면 시간을 처음부터 다시 잰다 (숨겨진 탭은 영원히 안 그려진다) */
  const arm = (ms: number) => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (document.hidden) {
        const again = () => { if (!document.hidden) { document.removeEventListener('visibilitychange', again); if (!disposed && mode === 'loading') arm(ms); } };
        document.addEventListener('visibilitychange', again);
        return;
      }
      toNext();
    }, ms);
  };

  void (async () => {
    arm(STYLE_TIMEOUT_MS);
    if (!hasWebGL()) { toNext(); return; }
    try {
      const [{maplibreGL}, ml] = await Promise.all([import('@maplibre/maplibre-gl-leaflet'), import('maplibre-gl')]);
      if (disposed || mode !== 'loading') return;
      // 타일을 해석하는 워커 파일 주소. 번들러가 만든 조각 주소로는 워커를 못 찾아서, 같은 출처로 내려 주는 사본을 가리킨다.
      // 사본은 scripts/copy-maplibre-worker.mjs가 node_modules에서 public/maplibre/로 복사한다(predev, prebuild)
      ml.setWorkerUrl(new URL('/maplibre/maplibre-gl-worker.mjs', window.location.origin).href);
      const l = maplibreGL({style: STYLE_URL, attributionControl: {customAttribution: ATTRIBUTION}, renderWorldCopies: false});
      // 어댑터는 크기가 바뀔 때 다음 화면 갱신에서 this._map을 읽는데, 그 사이 레이어가 지워지면 null이라 오류가 난다(지도가 사라지는 때와 겹침).
      // 같은 일을 하되 갱신 직전에 아직 지도에 붙어 있는지 확인하도록 이 인스턴스의 메서드만 바꾼다
      const g = l as unknown as GuardedLayer;
      g._transitionEnd = function () {
        L.Util.requestAnimFrame(() => {
          const m = this._map, glm = this._glMap;
          if (!m || !glm) return;
          const center = m.getCenter(), zoom = m.getZoom();
          this._resizeContainer();
          L.DomUtil.setTransform(glm._actualCanvas, m.latLngToContainerPoint(m.getBounds().getNorthWest()), 1);
          glm.once('moveend', () => { if (this._map) this._zoomEnd(); });
          glm.jumpTo({center, zoom: zoom - 1});
        });
      };
      layer = l.addTo(map);
      const gl = layer.getMaplibreMap();
      gl.on('style.load', () => { tune(gl); arm(TILE_TIMEOUT_MS); });
      // 타일이 한 장이라도 불러와지면 성공이다. 그 뒤의 오류나 느림으로는 되돌리지 않는다
      const ok = () => { if (!disposed && mode === 'loading') { mode = 'basemap'; clearTimeout(timer); } };
      // 타일 불러오기가 실패해도 sourcedata는 오므로, 상태가 loaded인 타일만 센다
      gl.on('sourcedata', (e) => { if ((e as unknown as {tile?: {state?: string}}).tile?.state === 'loaded') ok(); });
      // 스타일을 못 불러온 오류만 되돌림 사유다. 타일 한두 장 실패는 8초 대기에 맡긴다
      gl.on('error', (e) => { const x = e as unknown as {sourceId?: string; tile?: unknown}; if (mode === 'loading' && !x.sourceId && !x.tile && !gl.isStyleLoaded()) toNext(); });
      // 칸 크기가 바뀌면(슬라이드 인, 펼치기) Leaflet 크기와 MapLibre 캔버스를 함께 맞춘다. 칸이 처음엔 작거나 0이었다가 커지는 일이 흔하다
      observer = new ResizeObserver(() => { if (mode === 'loading' || mode === 'basemap') api.resize(); });
      observer.observe(map.getContainer());
    } catch { toNext(); }
  })();

  const api: Basemap = {
    get mode() { return mode; },
    resize() {
      try {
        map.invalidateSize({animate: false});
        const l = layer as unknown as GuardedLayer | null;
        if (!l?._map || !l._glMap) return;
        l._resizeContainer();
        l._glMap.resize();
      } catch { /* 지도가 이미 지워짐 */ }
    },
    dispose() {
      disposed = true; clearTimeout(timer); clearTimeout(staticTimer); observer?.disconnect();
      for (const t of staticLayers) { try { map.removeLayer(t); } catch { /* 지도가 먼저 지워졌으면 이미 정리됨 */ } }
      staticLayers = [];
      const l = layer; layer = null;
      if (l) { try { map.removeLayer(l); } catch { /* 지도가 먼저 지워졌으면 이미 정리됨 */ } }
    },
  };
  return api;
}
