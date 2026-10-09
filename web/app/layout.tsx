/** Root layout bundles fonts locally so the delivered app needs no font CDN.
 * 글꼴: Pretendard는 설치돼 있지 않아 Noto Sans KR(번들)로 쓴다. 고정폭은 B/L 번호용 IBM Plex Mono만 남겼다. */
import type {Metadata} from 'next';
import '@fontsource-variable/manrope';
import '@fontsource-variable/noto-sans-kr';
import '@fontsource/ibm-plex-mono/400.css';
import 'leaflet/dist/leaflet.css';
// 지도 바탕(MapLibre) 스타일. 한 번만 불러온다 (lib/basemap.ts)
import 'maplibre-gl/dist/maplibre-gl.css';
import './globals.css';
// 화면 영역별 CSS는 globals.css 뒤에 이 순서로 불러온다 (뒤에 오는 파일이 앞의 같은 선택자를 덮는다)
import './styles/chat.css';
import './styles/detail.css';
import './styles/compare-vessel.css';
import './styles/document.css';
import './styles/cargo-sheet.css';
import './styles/watch.css';
import './styles/settings.css';
import './styles/admin.css';
import './styles/entry.css';
import './styles/landing.css';
import './styles/sidebar.css';
import './styles/metrics.css';
import './styles/evidence.css';
import './styles/brand.css';  // 로그인한 뒤 화면을 랜딩 톤에 맞추는 마지막 덮개. 다른 화면 CSS보다 뒤에 둔다
import {AppProvider} from '@/components/AppProvider';
import {Shell} from '@/components/Shell';
export const metadata:Metadata={title:'Marvia',description:'B/L 하나로 내 화물이 제때 오는지 판정하고, 왜 그런지 근거까지 보여 드려요. 예시 데이터로 체험해 볼 수 있어요.'};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="ko"><body><AppProvider><Shell>{children}</Shell></AppProvider></body></html>;}
