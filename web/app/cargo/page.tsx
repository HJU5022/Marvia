/** 내 화물 현황 표 route (10-06). 표와 수정은 CargoSheet.tsx가 한다. */
import {CargoSheet} from '@/components/CargoSheet';
export default function CargoPage(){return <div className="page"><div className="page-heading"><div><span className="eyebrow">YOUR CARGO SHEET</span><h1>내 화물 현황<span className="accent-dot">.</span></h1><p>신용장별로 출항, 입항, 입고를 한눈에 확인하세요.</p></div></div><CargoSheet/></div>;}
