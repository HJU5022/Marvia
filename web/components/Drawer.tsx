'use client';
/** 오른쪽에서 열리는 상세 패널. 서류 사진 확인과 선박 자세히 보기에 쓴다 (Marvia_Claude_구현작업서 4절 6항, 5절 효과 명세).
 * AI 입력창은 여기로 옮기지 않는다. 입력은 홈 가운데에 그대로 있고, 드로어는 입력을 돕거나 한 대상을 자세히 볼 때만 연다.
 *
 * 접근성 (WAI-ARIA Authoring Practices, Dialog (Modal) 패턴):
 * - 열리면 닫기 버튼에 포커스, Tab은 패널 안에서만 돈다(포커스 트랩), Esc로 닫는다
 * - 뒤 화면(.app-shell)은 inert로 막아 마우스·키보드·스크린리더가 닿지 않게 한다
 * - 닫으면 열기 전 포커스(누른 버튼)로 돌아간다
 * 열림 효과(x 24→0 + 흐려짐 해제, 260ms)는 globals.css .drawer에 있고 prefers-reduced-motion이면 꺼진다.
 */
import {useEffect, useId, useRef, type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {X} from 'lucide-react';

const FOCUSABLE = 'button:not([disabled]),[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])';

export function Drawer({title, description, onClose, children, wide = false}: {
  title: string; description?: string; onClose: () => void; children: ReactNode; wide?: boolean;
}) {
  const titleId = useId();
  const panel = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const shell = document.querySelector<HTMLElement>('.app-shell');
    shell?.setAttribute('inert', '');
    panel.current?.querySelector<HTMLElement>('.drawer-close')?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { e.preventDefault(); closeRef.current(); return; }
      if (e.key !== 'Tab' || !panel.current) return;
      const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(x => x.getClientRects().length);
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      shell?.removeAttribute('inert');
      if (opener?.isConnected) opener.focus();
    };
  }, []);

  return createPortal(<div className="drawer-overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <section ref={panel} className={`drawer ${wide ? 'wide' : ''}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <header className="drawer-head">
        <div><h2 id={titleId}>{title}</h2>{description && <p>{description}</p>}</div>
        <button type="button" className="drawer-close" onClick={onClose} aria-label="패널 닫기"><X size={18}/></button>
      </header>
      {children}
    </section>
  </div>, document.body);
}
