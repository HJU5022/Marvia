/** E11 history route. 제목 옆의 "조회 이력" 테두리 글자는 메뉴·제목과 같은 말을 되풀이해 지웠다 (10-02 UI 점검 V8). */
import {HistoryTable} from '@/components/HistoryTable';
export default function HistoryPage(){return <div className="page"><div className="page-heading"><div><span className="eyebrow">YOUR CARGO LOGBOOK</span><h1>쌓이는 기록, 선명한 판단<span className="accent-dot">.</span></h1><p>지난 조회와 그때의 근거를 다시 살펴보세요.</p></div></div><HistoryTable/></div>;}
