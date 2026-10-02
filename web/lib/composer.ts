/** 다른 카드에서 AI 입력창으로 돌아가게 하는 통로 (Marvia_Claude_구현작업서 4절 5항 "AI 입력으로 돌아가는 버튼").
 * 예: 첫 화면 작업 카드, ETA 카드의 "AI에게 근거 묻기", 지원 범위 밖 안내의 "질문 고치기".
 * 입력창(ChatBar)이 이 이벤트를 듣고 글자를 채운 뒤 포커스한다. 보내기는 사용자가 한다. 예시를 눌러도 유료 호출이 바로 나가지 않게 한다.
 * 상태 저장소(AppProvider)에 넣지 않은 이유: 입력 중인 글자는 화면 하나의 일이고, 응답 데이터와 섞이면 안 된다.
 */
const EVENT = 'marvia:compose';

/** 입력창으로 이동한다. text를 주면 입력창 글자를 그것으로 바꾼다 */
export function focusComposer(text?: string) {
  window.dispatchEvent(new CustomEvent<string | undefined>(EVENT, {detail: text}));
}

/** 입력창이 듣는다. 돌려준 함수로 듣기를 끝낸다 */
export function onComposerRequest(handler: (text: string | undefined) => void) {
  // detail을 비워 보내면 브라우저는 undefined가 아니라 null을 준다. 글자가 아닌 값은 "채울 글자 없음"으로 넘긴다
  const listener = (e: Event) => { const d = (e as CustomEvent<unknown>).detail; handler(typeof d === 'string' ? d : undefined); };
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}
