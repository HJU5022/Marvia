"use client";
// Marvia 화면 한 쪽 (설계 10절, 계획 9): v1의 틀(위 줄, 대화 왼쪽, 상세 오른쪽 40:60, 좁으면 시트) 안에
// 채팅, 계획 진행, 이렇게 읽었어요, 선택지·승인 카드, 답과 근거, 화물 카드를 둔다.
// 상태는 서버가 보낸 STATE_SNAPSHOT(허용 목록)과 답 글뿐이다. 서버에 state를 보내지 않는다.
import { ChevronUp, CircleAlert, LoaderCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApprovalCardView } from "@/components/ApprovalCardView";
import { CargoCards } from "@/components/CargoCards";
import { ChoiceCardView } from "@/components/ChoiceCardView";
import { Composer } from "@/components/Composer";
import { LoginScreen } from "@/components/LoginScreen";
import { EvidencePanel, PlanList, ReadingList } from "@/components/Panels";
import { TopBar } from "@/components/TopBar";
import { type AgUiEvent, type Card, deleteAccount, EMPTY_VIEW, HttpError, newId, runTurn, type View } from "@/lib/agui";
import { currentToken, signOut } from "@/lib/auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
type Line = { role: "user" | "assistant"; text: string; id?: string };

// 입력창을 채우기만 한다(보내기는 사용자가 한다, v1 규칙). 번호는 넣지 않는다
const EXAMPLES = ["수입신고는 언제까지 해야 해요?", "장치기간이 궁금해요", "화물관리번호로 상태를 보고 싶어요"];

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [threadId, setThreadId] = useState(newId);
  const [lines, setLines] = useState<Line[]>([]);
  const [view, setView] = useState<View>(EMPTY_VIEW);
  const [card, setCard] = useState<Card | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false); // 900px 이하에서 상세 시트가 펼쳐졌는지

  const running = useRef<AbortController | null>(null);
  const sending = useRef(false); // [왜] busy는 상태라 빠른 두 번 입력 사이에 아직 안 바뀐다
  const scroller = useRef<HTMLDivElement>(null);

  // 화면을 떠나면 진행 중인 차례를 멈춘다
  useEffect(() => () => running.current?.abort(), []);

  useEffect(() => {
    currentToken().then(setToken);
  }, []);

  const onEvent = useCallback((event: AgUiEvent) => {
    // [왜] 카드는 이어받은 차례의 첫 이벤트가 올 때 치운다. 연결이 실패하면 카드가 남아 다시 할 수 있다
    if (event.type === "RUN_STARTED") setCard(null);
    if (event.type === "STATE_SNAPSHOT") setView(event.snapshot);
    if (event.type === "TEXT_MESSAGE_CONTENT") {
      // 같은 messageId의 조각은 한 줄에 이어 붙인다
      setLines((old) =>
        old.some((l) => l.id === event.messageId)
          ? old.map((l) => (l.id === event.messageId ? { ...l, text: l.text + event.delta } : l))
          : [...old, { role: "assistant", text: event.delta, id: event.messageId }],
      );
    }
    if (event.type === "RUN_ERROR") setError(event.message);
    if (event.type === "RUN_FINISHED" && event.outcome?.type === "interrupt") {
      const pending = event.outcome.interrupts[0];
      setCard({ ...pending.metadata, id: pending.id });
    }
  }, []);

  const turn = useCallback(
    async (input: { text?: string; resume?: { interruptId: string; payload: unknown } }) => {
      if (!token || sending.current) return;
      sending.current = true;
      setBusy(true);
      setError("");
      // [왜] 토큰은 차례마다 새로 받는다. Supabase는 만료 직전이면 갱신한 토큰을 주므로 1시간 뒤에도 로그인이 이어진다
      const fresh = await currentToken();
      if (!fresh) {
        sending.current = false;
        setBusy(false);
        setToken(null);
        setError("다시 로그인해 주세요");
        return;
      }
      running.current?.abort();
      const controller = new AbortController();
      running.current = controller;
      try {
        await runTurn(API_URL, fresh, { threadId, ...input }, onEvent, controller.signal);
      } catch (failure) {
        if (controller.signal.aborted) return; // 멈춘 차례는 아무것도 보이지 않는다
        // [왜] fetch가 연결 실패로 던지는 TypeError는 영어 글이다. 정해 둔 한글로 바꾼다
        setError(
          failure instanceof Error && !(failure instanceof TypeError)
            ? failure.message
            : "서버에 닿지 못했어요. 잠시 뒤 다시 해 주세요",
        );
        // [왜] 카드는 서버가 지난 카드라고 할 때(stale_card)만 치운다. 답하는 중·계정 삭제 중(409)과
        //      422는 카드가 아직 살아 있어 다시 보낼 수 있다
        if (failure instanceof HttpError && failure.code === "stale_card") setCard(null);
        if (failure instanceof HttpError && failure.status === 401) signOut().then(() => setToken(null));
      } finally {
        sending.current = false;
        if (running.current === controller) setBusy(false);
      }
    },
    [token, threadId, onEvent],
  );

  function send() {
    const text = draft.trim();
    if (!text || busy || sending.current) return;
    setLines((old) => [...old, { role: "user", text }]);
    setDraft("");
    turn({ text });
  }

  async function removeAccount() {
    setConfirmingDelete(false);
    const fresh = await currentToken();
    if (!fresh) return setToken(null);
    try {
      await deleteAccount(API_URL, fresh);
      running.current?.abort();
      await signOut();
      // [왜] 지운 계정의 대화·카드·패널이 다음 로그인 화면에 남지 않게 화면 상태도 비운다
      setLines([]);
      setView(EMPTY_VIEW);
      setCard(null);
      setDraft("");
      setBusy(false);
      setThreadId(newId()); // 지운 대화 id로 다음 차례를 보내지 않는다
      setToken(null);
      setError("계정을 지웠어요. 대화 기록과 저장한 값이 모두 지워졌어요");
    } catch (failure) {
      // [왜] 409(답하는 중, 지우는 중)는 서버가 정한 글을 그대로 보인다
      setError(failure instanceof HttpError ? failure.message : "서버에 닿지 못했어요. 잠시 뒤 다시 해 주세요");
      // [왜] 차례 보내기와 같다. 토큰이 만료됐거나 틀리면 로그인 화면으로 간다
      if (failure instanceof HttpError && failure.status === 401) signOut().then(() => setToken(null));
    }
  }

  const reply = useCallback(
    (payload: unknown) => {
      if (card) turn({ resume: { interruptId: card.id, payload } });
    },
    [card, turn],
  );

  const hasDetail = view.plan.length + view.reading.length + view.cargos.length + view.evidence.length > 0;
  // 결과가 처음 생기면 좁은 화면에서도 시트를 펼쳐 보인다. 입력창을 누르면 접힌다(키보드가 가리지 않게)
  useEffect(() => setSheetOpen(hasDetail), [hasDetail]);
  // 새 줄이나 카드가 생기면 대화 칸을 맨 아래로 내린다
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [lines, card, busy, error]);

  if (!token) return <LoginScreen error={error} onError={setError} onToken={setToken} />;

  return (
    <div className="app">
      <TopBar
        confirming={confirmingDelete}
        onSignOut={() => {
          running.current?.abort();
          signOut().then(() => setToken(null));
        }}
        onAskDelete={() => setConfirmingDelete(true)}
        onDelete={removeAccount}
        onCancelDelete={() => setConfirmingDelete(false)}
      />
      <main className={`chat-app${hasDetail ? " split" : ""}`}>
        <section className="chat-pane" aria-labelledby="chat-title">
          <h2 id="chat-title" className="sr-only">
            대화
          </h2>
          <div className="chat-scroll" ref={scroller}>
            {lines.length === 0 && !card && !busy ? (
              <div className="empty">
                <h2>어떤 화물이 궁금하세요?</h2>
                <p className="lead">B/L이나 화물관리번호를 적거나, 수입 통관 법령을 물어보세요. 답마다 근거를 함께 보여 드려요.</p>
                <ul className="examples">
                  {EXAMPLES.map((example) => (
                    <li key={example}>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => {
                          setDraft(example);
                          document.getElementById("question")?.focus();
                        }}
                      >
                        {example}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <ol className="chat" aria-live="polite">
              {lines.map((line, i) => (
                <li key={i} data-role={line.role}>
                  <span className="who">{line.role === "user" ? "나" : "Marvia"}</span>
                  <p className="text">{line.text}</p>
                </li>
              ))}
            </ol>
            <p role="status" aria-live="polite" className="status">
              {busy ? (
                <>
                  <LoaderCircle size={16} className="spin" aria-hidden="true" />
                  답하는 중이에요
                </>
              ) : (
                ""
              )}
            </p>
            {error ? (
              <p role="alert" className="notice">
                <CircleAlert size={16} aria-hidden="true" />
                {error}
              </p>
            ) : null}
            {card?.kind === "choice" ? <ChoiceCardView key={card.id} card={card} onReply={reply} /> : null}
            {card?.kind === "approval" ? <ApprovalCardView key={card.id} card={card} onReply={reply} /> : null}
          </div>
          <Composer draft={draft} busy={busy} onDraft={setDraft} onSend={send} onFocus={() => setSheetOpen(false)} />
        </section>
        {hasDetail ? (
          <aside className="detail-pane" aria-label="상세" data-open={sheetOpen}>
            <button
              type="button"
              className="sheet-handle"
              aria-expanded={sheetOpen}
              aria-controls="detail-body"
              onClick={() => setSheetOpen((open) => !open)}
            >
              <span>{sheetOpen ? "상세 접기" : "상세 보기"}</span>
              <ChevronUp size={16} aria-hidden="true" style={{ transform: sheetOpen ? "rotate(180deg)" : "none" }} />
            </button>
            <div id="detail-body" className="detail-body">
              <PlanList plan={view.plan} />
              <ReadingList reading={view.reading} />
              <CargoCards cargos={view.cargos} />
              <EvidencePanel evidence={view.evidence} />
            </div>
          </aside>
        ) : null}
      </main>
    </div>
  );
}
