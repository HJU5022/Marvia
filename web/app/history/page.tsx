/** E11 history route. 조회 이력은 /settings의 "조회 이력" 탭과 같은 화면이다. 제목은 왼쪽 위, 그 아래 한 줄 설명. */
import {HistoryTable} from '@/components/HistoryTable';
export default function HistoryPage(){return <div className="page st-page"><header className="st-head"><h1>조회 이력</h1><p>최근 조회한 내용을 요약으로 볼 수 있어요. 자세한 근거는 다시 조회하면 확인할 수 있어요.</p></header><HistoryTable/></div>;}
