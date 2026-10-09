/** 감시·지도 화면 (docs/specs/cargo-watch.md). 왼쪽 메뉴 "내 화물" 드롭다운의 두 번째 항목이다 */
import {WatchMap} from '@/components/WatchMap';
import {WatchedVessels} from '@/components/WatchedVessels';
// B/L 없이 배만 지켜보는 줄은 지도 아래에 따로 보인다 (판정 없음)
export default function WatchPage(){return <div className="page"><WatchMap/><WatchedVessels/></div>;}
