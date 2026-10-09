// MapLibre 워커 파일을 public/maplibre/로 복사한다 (승인, lib/basemap.ts 참고).
// 이유: 번들러(Turbopack)가 만든 조각 주소로는 워커를 못 찾는다. 같은 출처의 고정 주소로 내려 주려고 node_modules의 파일을 그대로 복사한다.
// 워커는 같은 폴더의 maplibre-gl-shared.mjs를 불러오므로 둘 다 복사한다. 버전이 바뀌어도 npm install 뒤 predev/prebuild가 다시 복사한다.
import {copyFileSync, mkdirSync} from 'node:fs';
const from = new URL('../node_modules/maplibre-gl/dist/', import.meta.url), to = new URL('../public/maplibre/', import.meta.url);
mkdirSync(to, {recursive: true});
for (const f of ['maplibre-gl-worker.mjs', 'maplibre-gl-shared.mjs']) copyFileSync(new URL(f, from), new URL(f, to));
// BSD-3 라이선스 문구는 파일 머리말에 들어 있어 따로 복사하지 않는다
console.log('maplibre worker copied to public/maplibre/');
