# Bundled assets and libraries

- **Leaflet 1.9.4** - BSD-2-Clause. https://leafletjs.com / https://github.com/Leaflet/Leaflet/blob/main/LICENSE
- **Natural Earth geography via world-atlas 2.0.2** - public domain. `countries-10m.json`에서 한국·북한·일본·중국·대만 지형을 GeoJSON으로 변환해 `lib/fixtures/geography.json`에 저장했습니다. https://www.naturalearthdata.com/about/terms-of-use/ / https://github.com/topojson/world-atlas
- **topojson-client** - ISC. 지형 변환에 사용했습니다. https://github.com/topojson/topojson-client
- **Manrope / Noto Sans KR / IBM Plex Mono** - SIL Open Font License 1.1. Fontsource npm 패키지의 라이선스와 폰트를 로컬 번들로 사용합니다. https://fontsource.org
- **Lucide** - ISC. https://lucide.dev/license
- **Next.js / React** - MIT. https://nextjs.org / https://react.dev
- **MapLibre GL JS 6** - BSD-3-Clause. 세계지도 그리기(WebGL). https://github.com/maplibre/maplibre-gl-js/blob/main/LICENSE.txt
- **@maplibre/maplibre-gl-leaflet** - ISC. MapLibre 지도를 Leaflet 레이어로 얹는다. https://github.com/maplibre/maplibre-gl-leaflet
- **OpenFreeMap (positron 스타일, 벡터 타일)** - 무료 공개 서비스, 키 없음. 지도 데이터는 **© OpenStreetMap contributors, ODbL 1.0**. 화면에 "© OpenStreetMap · OpenFreeMap"을 표시합니다. https://openfreemap.org / https://www.openstreetmap.org/copyright
- **미리 구운 지도 조각 `public/basemap/`** - 위 OpenFreeMap 지도를 같은 스타일로 그려 저장한 그림(WebGL 없는 PC용, `scripts/bake-basemap.mjs`). OpenStreetMap 데이터로 만든 결과물이라 같은 출처 표시를 따릅니다.

지도에는 쓰는 바탕에 따라 "© OpenStreetMap · OpenFreeMap" 또는 Natural Earth 출처를 표시합니다. ShipFinder·UNI-PASS·해수부 실제 응답과 원본 프로젝트 자산을 복사하지 않았습니다. 화면에 표시된 해당 출처명은 가공 fixture의 근거 유형입니다.

Next.js 공식 설치·라우팅 문서와 Leaflet 공식 레퍼런스를 확인해 구성했습니다:
https://nextjs.org/docs/app/getting-started/installation
https://leafletjs.com/reference.html
