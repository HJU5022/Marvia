"use client";
// 입력창 (v1 ChatBar의 규칙): Enter로 보내고, Shift+Enter는 줄바꿈, 한글 조합 중 Enter는 무시, 서버 상한까지.
import { SendHorizontal } from "lucide-react";

// [왜] 서버가 받는 글 한 번의 상한(rules/server.yaml request.max_text)과 같게 둔다. 넘으면 서버가 422로 거절한다.
//      같은 값인지는 tests/test_web_composer_limit.py가 본다 (v1의 500자는 v1 서버 값이었다)
export const MAX_CHARS = 2000;

export function Composer({
  draft,
  busy,
  onDraft,
  onSend,
  onFocus,
}: {
  draft: string;
  busy: boolean;
  onDraft: (text: string) => void;
  onSend: () => void;
  onFocus: () => void;
}) {
  return (
    <div className="composer-wrap">
      <form
        className="ask"
        onSubmit={(e) => {
          e.preventDefault();
          onSend();
        }}
      >
        <label htmlFor="question" className="sr-only">
          질문이나 화물 단서 (B/L·화물관리번호)
        </label>
        <textarea
          id="question"
          rows={2}
          maxLength={MAX_CHARS}
          placeholder="질문이나 화물 단서를 적어 주세요 (Enter로 보내기, Shift+Enter로 줄바꿈)"
          value={draft}
          onFocus={onFocus}
          onChange={(e) => onDraft(e.target.value)}
          onKeyDown={(e) => {
            // [주의] 한글 조합 중 Enter는 글자를 확정하는 키다. 그때 보내면 마지막 글자가 남거나 두 번 간다
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              onSend();
            }
          }}
        />
        <div className="ask-foot">
          <span className="meta" aria-hidden="true">
            {draft.length}/{MAX_CHARS}
          </span>
          <button type="submit" disabled={busy || !draft.trim()}>
            <SendHorizontal size={16} aria-hidden="true" />
            보내기
          </button>
        </div>
      </form>
    </div>
  );
}
