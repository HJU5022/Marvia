"use client";

// 주선자 화면. 왼쪽 지도, 오른쪽 채팅. 응답 stage 에 따라 화면이 갈린다 (SDD 2절).

import { useCallback, useMemo, useRef, useState } from "react";
import AuthGate, { UserBar } from "@/components/AuthGate";
import ChatPanel, { type ChatMessage, type ChatSend } from "@/components/ChatPanel";
import MapView from "@/components/MapView";
import { canEdit, pinsFrom, type Viewer } from "@/components/ParticipantPins";
import ResultTable from "@/components/ResultTable";
import { authHeaders, useAuth } from "@/lib/auth";
import type { AgentRequest, AgentResponse } from "@/types/agent";

const ORGANIZER: Viewer = { role: "organizer" };

export default function Home() {
  const auth = useAuth();
  return (
    <main className="app">
      <header className="topbar">
        <strong>Converge</strong>
        <span className="muted">현장 집결 장소·시각 정하기</span>
        <UserBar auth={auth} />
      </header>
      <AuthGate auth={auth} reason="Converge 는 구글 로그인 후 쓸 수 있습니다.">
        <Organizer headers={authHeaders(auth)} />
      </AuthGate>
    </main>
  );
}

function Organizer({ headers }: { headers: Record<string, string> }) {
  const [response, setResponse] = useState<AgentResponse | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [moved, setMoved] = useState<Record<string, [number, number]>>({});
  const [selectedRank, setSelectedRank] = useState<number | null>(null);
  const lastRequest = useRef<AgentRequest | null>(null);
  const seq = useRef(0);
  const headerKey = JSON.stringify(headers);

  const push = useCallback((m: Omit<ChatMessage, "id">) => {
    seq.current += 1;
    const id = seq.current;
    setMessages((list) => [...list, { ...m, id }]);
  }, []);

  const call = useCallback(
    async (body: AgentRequest) => {
      lastRequest.current = body;
      setBusy(true);
      try {
        const res = await fetch("/api/agent", {
          method: "POST",
          headers: { "Content-Type": "application/json", ...JSON.parse(headerKey) },
          body: JSON.stringify(body),
        });
        if (res.status === 401) throw new Error("로그인이 만료됐습니다. 다시 로그인해 주세요.");
        if (res.status === 403) throw new Error("이 세션을 고칠 권한이 없습니다.");
        if (res.status === 409) throw new Error("약속 날짜가 지나 잠긴 세션입니다.");
        if (!res.ok) throw new Error(`요청이 실패했습니다 (${res.status}). 잠시 후 다시 시도해 주세요.`);
        const data = (await res.json()) as AgentResponse;
        setResponse(data);
        setMoved({});
        const firstRank = data.result?.candidates
          .map((c) => c.rank)
          .filter((r): r is number => r !== null)
          .sort((a, b) => a - b)[0];
        setSelectedRank(firstRank ?? null);
        push({
          role: data.stage === "failed" ? "error" : "agent",
          text: data.message,
          questions: data.stage === "need_info" ? data.questions : undefined,
        });
      } catch (e) {
        push({ role: "error", text: (e as Error).message });
      } finally {
        setBusy(false);
      }
    },
    [headerKey, push],
  );

  const onSend = (input: ChatSend) => {
    push({ role: "user", text: input.text ?? "(캡처)", image: Boolean(input.image_base64) });
    void call({
      session_id: response?.session_id ?? null,
      text: input.text,
      image_base64: input.image_base64,
      preset: input.preset,
      confirmed_participants: null,
    });
  };

  const pins = useMemo(() => pinsFrom(response, moved), [response, moved]);

  const onMove = useCallback(
    (name: string, lng: number, lat: number) => {
      const pin = pins.find((p) => p.name === name);
      if (!pin || !canEdit(ORGANIZER, pin.owner_user_id)) return;
      setMoved((m) => ({ ...m, [name]: [lng, lat] }));
    },
    [pins],
  );

  const recompute = () => {
    const prev = lastRequest.current;
    void call({
      session_id: response?.session_id ?? null,
      text: prev?.text ?? "핀 위치 확인",
      image_base64: null,
      preset: prev?.preset ?? null,
      // 참석자 본인 소유 핀은 보내지 않는다. 서버가 남의 핀 수정으로 보고 403 을 낸다 (SDD 5절 2-1)
      confirmed_participants: pins
        .filter((p) => canEdit(ORGANIZER, p.owner_user_id))
        .map((p) => ({ name: p.name, lng: p.lng, lat: p.lat })),
    });
  };

  const retry = () => {
    if (lastRequest.current) void call(lastRequest.current);
  };

  const stage = response?.stage;
  const movedCount = Object.keys(moved).length;
  const lockedCount = pins.filter((p) => !canEdit(ORGANIZER, p.owner_user_id)).length;

  return (
    <div className="split">
      <div className="split-map">
        <MapView
          response={stage === "need_info" || stage === "out_of_scope" ? null : response}
          participantPins={pins}
          viewer={ORGANIZER}
          selectedRank={selectedRank}
          onSelectRank={setSelectedRank}
          onMove={onMove}
        />
      </div>
      <div className="split-side">
        <ChatPanel messages={messages} busy={busy} onSend={onSend}>
          {stage === "need_confirm" && (
            <div className="step">
              <p>
                <strong>위치가 맞나요?</strong> 주황 핀은 위치가 불확실합니다. 핀을 끌어서 고친 뒤 계산하세요.
              </p>
              {lockedCount > 0 && (
                <p className="muted">회색 핀은 참석자 본인이 등록한 위치라 주선자가 옮길 수 없습니다.</p>
              )}
              <button type="button" className="primary" disabled={busy} onClick={recompute}>
                이 위치로 계산
              </button>
            </div>
          )}
          {stage === "done" && movedCount > 0 && (
            <div className="step">
              <p>핀 {movedCount}개를 옮겼습니다.</p>
              <button type="button" className="primary" disabled={busy} onClick={recompute}>
                바뀐 위치로 다시 계산
              </button>
            </div>
          )}
          {stage === "failed" && (
            <div className="step">
              <button type="button" disabled={busy} onClick={retry}>
                다시 시도
              </button>
            </div>
          )}
          {stage === "out_of_scope" && (
            <div className="step notice">
              Converge 는 출발 전 집결 장소와 시각만 정합니다. 출발 후 실시간 상황은 다루지 않습니다.
            </div>
          )}
        </ChatPanel>

        {stage === "done" && response?.result && (
          <>
            <ResultTable
              result={response.result}
              participants={response.slots.participants}
              selectedRank={selectedRank}
              onSelectRank={setSelectedRank}
            />
            <ShareBox sessionId={response.session_id} />
          </>
        )}
      </div>
    </div>
  );
}

function ShareBox({ sessionId }: { sessionId: string }) {
  const [copied, setCopied] = useState(false);
  const url = typeof window === "undefined" ? `/s/${sessionId}` : `${window.location.origin}/s/${sessionId}`;
  return (
    <section className="share">
      <h3>참석자에게 공유</h3>
      <div className="share-row">
        <input readOnly value={url} onFocus={(e) => e.target.select()} />
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard?.writeText(url).then(() => setCopied(true));
          }}
        >
          {copied ? "복사됨" : "복사"}
        </button>
      </div>
      <p className="muted">
        링크를 받은 사람은 구글 로그인 후 참석자 이름·출발지·집결지 위치를 볼 수 있습니다. 참석자가 자기를 고르면 그 핀은
        본인만 옮길 수 있습니다.
      </p>
    </section>
  );
}
