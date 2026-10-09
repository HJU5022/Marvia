'use client';
/** 약관·처리방침을 띄우는 작은 창. 가운데 가는 제목, 본문, 맨 아래 사각 외곽선 닫기 버튼 하나.
 * 접근성: role=dialog + aria-modal, 열면 창 안으로 포커스를 옮기고 Tab이 밖으로 못 나가게 가둔다.
 * Esc·바깥 클릭·X·닫기 버튼으로 닫고, 닫으면 눌렀던 버튼으로 포커스를 돌려준다. 스타일은 app/styles/entry.css (legal-*).
 */
import {useEffect, useRef, type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {X} from 'lucide-react';

export function LegalModal({title, onClose, children}: {title: string; onClose: () => void; children: ReactNode}) {
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;  // 닫을 때 돌아갈 곳
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';  // 뒤 화면이 같이 스크롤되지 않게
    box.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); return; }
      if (e.key !== 'Tab' || !box.current) return;
      // 포커스 가두기: 창 안의 눌 수 있는 것 사이에서만 돈다
      const items = box.current.querySelectorAll<HTMLElement>('button,a[href],[tabindex]:not([tabindex="-1"])');
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === box.current)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = overflow; before?.focus(); };
  }, [onClose]);

  // 앱 틀(transform 등)의 영향을 받지 않도록 body 바로 아래에 그린다
  return createPortal(
    <div className="legal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="legal-modal" role="dialog" aria-modal="true" aria-labelledby="legal-title" ref={box} tabIndex={-1}>
        <button type="button" className="legal-x" aria-label="닫기" onClick={onClose}><X size={18} strokeWidth={1.2}/></button>
        <h2 id="legal-title">{title}</h2>
        <div className="legal-body">{children}</div>
        <button type="button" className="legal-close" onClick={onClose}>닫기</button>
      </div>
    </div>,
    document.body);
}
