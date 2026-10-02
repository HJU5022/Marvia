'use client';
/** 운영자 전용 화면의 문 (docs/specs/operator-admin.md). 사이드바는 운영자에게만 탭을 보여 주지만,
 * 주소로 바로 들어오는 경우를 여기서 막는다. 데이터 권한은 서버가 따로 확인한다 (화면 숨김은 편의).
 */
import type {ReactNode} from 'react';
import {ShieldUser} from 'lucide-react';
import {useApp} from './AppProvider';

export function OperatorOnly({children}: {children: ReactNode}) {
  const {isOperator, authReady, meReady} = useApp();
  if (!authReady || !meReady) {
    return <div className="page"><div className="initial-loading" role="status"><div className="loading-orbit"/><strong>권한을 확인하고 있어요.</strong></div></div>;
  }
  if (!isOperator) {
    return <div className="page"><div className="empty-state admin-denied"><ShieldUser size={34} strokeWidth={1.2}/><h2>운영자만 볼 수 있는 화면입니다.</h2><p>권한이 필요하면 기존 운영자에게 등록을 요청하세요.</p></div></div>;
  }
  return <>{children}</>;
}
