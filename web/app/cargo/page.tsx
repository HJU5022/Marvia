/** 내 화물 현황 표 route. 제목, 표, 수정은 모두 CargoSheet.tsx가 한다(엑셀 받기 버튼이 제목과 같은 줄이라서). */
import {CargoSheet} from '@/components/CargoSheet';
export default function CargoPage(){return <div className="page cargo-page"><CargoSheet/></div>;}
