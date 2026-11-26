"use client";
// 위 줄 (v1 TopBar/Shell의 틀): 로고, 로그아웃, 계정 삭제. 삭제 확인은 위 줄 아래에 펼친다(모달이 아니다).
// [왜] v2에는 v1 사이드바가 가리킬 쪽(기록, 감시, 설정)이 없어 위 줄 하나만 둔다.
import { LogOut, Ship, Trash2 } from "lucide-react";
import { useEffect, useRef } from "react";

export function TopBar({
  confirming,
  onSignOut,
  onAskDelete,
  onDelete,
  onCancelDelete,
}: {
  confirming: boolean;
  onSignOut: () => void;
  onAskDelete: () => void;
  onDelete: () => void;
  onCancelDelete: () => void;
}) {
  const confirmBox = useRef<HTMLDivElement>(null);
  // 계정 삭제 확인이 뜨면 초점을 옮긴다. 누른 버튼이 사라져 초점이 문서 처음으로 가지 않게 한다
  useEffect(() => {
    if (confirming) confirmBox.current?.focus();
  }, [confirming]);

  return (
    <>
      <header className="topbar">
        <h1 className="brand">
          <Ship size={20} aria-hidden="true" />
          Marvia
        </h1>
        <div className="account">
          {confirming ? null : (
            <button type="button" className="quiet" aria-label="계정 삭제" onClick={onAskDelete}>
              <Trash2 size={16} aria-hidden="true" />
              <span>계정 삭제</span>
            </button>
          )}
          <button type="button" className="quiet" aria-label="로그아웃" onClick={onSignOut}>
            <LogOut size={16} aria-hidden="true" />
            <span>로그아웃</span>
          </button>
        </div>
      </header>
      {confirming ? (
        <div
          ref={confirmBox}
          className="confirm-bar"
          tabIndex={-1}
          role="group"
          aria-label="계정 삭제 확인"
          aria-describedby="delete-warning"
        >
          <p id="delete-warning">계정을 지우면 대화 기록, 저장한 값, 감시 목록이 모두 지워지고 되돌릴 수 없어요. 지울까요?</p>
          <div className="row">
            <button type="button" onClick={onDelete}>
              지우기
            </button>
            <button type="button" className="secondary" onClick={onCancelDelete}>
              그만두기
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
