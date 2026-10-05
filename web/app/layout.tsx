/** Root layout bundles fonts locally so the delivered app needs no font CDN. */
import type {Metadata} from 'next';
import '@fontsource-variable/noto-sans-kr';
import '@fontsource-variable/manrope';
import '@fontsource/ibm-plex-mono/400.css';
import 'leaflet/dist/leaflet.css';
import './globals.css';
import {AppProvider} from '@/components/AppProvider';
import {Shell} from '@/components/Shell';
export const metadata:Metadata={title:'Marvia',description:'B/L 하나로 내 화물이 제때 오는지 판정하고, 왜 그런지 근거까지 보여줍니다. 가공 데이터 데모.'};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="ko"><body><AppProvider><Shell>{children}</Shell></AppProvider></body></html>;}
