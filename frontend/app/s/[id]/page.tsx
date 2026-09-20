"use client";

// 참석자들이 모이는 자리. 메인에서 문장을 넣으면 이 주소가 만들어지고, 그 주소를 단톡방에 전달한다.
// 되묻기, 핀 확인, 결과 보기, 자기 이름 고르기(claim), 출발지 수정이 전부 여기서 일어난다 (09-20 구조).
//
// 로그인한 사람이면 링크를 아는 누구나 들어온다. 정원으로 막지 않는다. 참석자는 언제든 늘 수 있기 때문이다.
// 막는 것은 없는 링크와 만료된 링크뿐이고, 그때는 "잘못된 경로" 화면을 보여 준다.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AuthGate, { UserBar } from "@/components/AuthGate";
import ChatPanel, { type ChatMessage, type ChatSend } from "@/components/ChatPanel";
import MapView from "@/components/MapView";
import { pinsFrom, type Viewer } from "@/components/ParticipantPins";
import ResultTable from "@/components/ResultTable";
import { authHeaders, useAuth, type AuthState } from "@/lib/auth";
import type {
  AgentRequest,
  AgentResponse,
  ParticipantEdit,
  ParticipantPatchRequest,
  ParticipantPatchResponse,
} from "@/types/agent";

const ERRORS: Record<number, string> = {
  401: "로그인이 만료됐습니다. 다시 로그인해 주세요.",
  403: "이 계획을 고칠 권한이 없습니다.",
  409: "이미 다른 사람이 등록했거나, 약속 날짜가 지나 잠긴 계획입니다.",
};

// "누가 마지막에 고쳤는지" 한 줄. 표에는 user_id 만 남아 이름을 말할 수 없으므로 관계로만 말한다.
function editedLabel(edit: ParticipantEdit | undefined, userId: string): string | null {
  if (!edit?.edited_by) return null;
  const who = edit.edited_by === userId ? "내가" : edit.by_owner ? "본인이" : "다른 사람이";
  const when = edit.edited_at
    ? new Date(edit.edited_at).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" })
    : "";
  return `${who} 고침${when ? ` · ${when}` : ""}`;
}

export default function SharePage() {
  const auth = useAuth();
  const { id } = useParams<{ id: string }>();
  return (
    <main className="app">
      <header className="topbar">
        <Link href="/" className="brand">
          Converge
        </Link>
        <span className="muted">집결 계획</span>
        <Link href="/my" className="topbar-link">
          내 계획
        </Link>
        <UserBar auth={auth} />
      </header>
      <AuthGate auth={auth} reason="집결 계획은 구글 로그인 후 볼 수 있습니다.">
        {auth.status === "signed_in" && <Plan sessionId={id} auth={auth} />}
      </AuthGate>
    </main>
  );
}

function Plan({ sessionId, auth }: { sessionId: string; auth: AuthState }) {
  const userId = auth.status === "signed_in" ? auth.userId : "";
  const headerKey = JSON.stringify(authHeaders(auth));
  const [response, setResponse] = useState<AgentResponse | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [moved, setMoved] = useState<Record<string, [number, number]>>({});
  const [selectedRank, setSelectedRank] = useState<number | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const seq = useRef(0);
  const viewer: Viewer = useMemo(() => ({ role: "participant", userId }), [userId]);

  const push = useCallback((m: Omit<ChatMessage, "id">) => {
    seq.current += 1;
    const id = seq.current;
    setMessages((list) => [...list, { ...m, id }]);
  }, []);

  const apply = useCallback(
    (data: AgentResponse, silent = false) => {
      setResponse(data);
      setMoved({});
      const first = data.result?.candidates
        .map((c) => c.rank)
        .filter((r): r is number => r !== null)
        .sort((a, b) => a - b)[0];
      setSelectedRank(first ?? null);
      if (data.message && !silent) {
        push({
          role: data.stage === "failed" ? "error" : "agent",
          text: data.message,
          questions: data.stage === "need_info" ? data.questions : undefined,
        });
      }
    },
    [push],
  );

  // 첫 진입: 메인에서 넘겨 준 응답이 있으면 그것을 쓰고, 없으면 서버에서 읽는다
  useEffect(() => {
    let alive = true;
    let handed: AgentResponse | null = null;
    try {
      const raw = sessionStorage.getItem(`converge:first:${sessionId}`);
      if (raw) {
        handed = JSON.parse(raw) as AgentResponse;
        sessionStorage.removeItem(`converge:first:${sessionId}`);
      }
    } catch {
      handed = null;
    }
    if (handed) {
      // 메인에서 막 만든 계획이다. 서버 안내 문구("주선자가 공유한 집결 계획입니다")는 띄우지 않는다
      apply(handed);
      return;
    }

    fetch(`/api/session/${encodeURIComponent(sessionId)}`, {
      headers: JSON.parse(headerKey),
      cache: "no-store",
    })
      .then(async (res) => {
        if (res.status === 404) {
          if (alive) setNotFound(true);
          return null;
        }
        if (!res.ok) throw new Error(ERRORS[res.status] ?? `불러오지 못했습니다 (${res.status})`);
        return (await res.json()) as AgentResponse;
      })
      .then((data) => {
        if (alive && data) apply(data, true);
      })
      .catch((e: Error) => alive && setLoadError(e.message));
    return () => {
      alive = false;
    };
  }, [sessionId, headerKey, apply]);

  const pins = useMemo(() => pinsFrom(response, moved), [response, moved]);
  const participants = response?.slots?.participants ?? [];
  const mine = participants.find((p) => p.owner_user_id === userId) ?? null;
  const stage = response?.stage;

  // 되묻기에 답하거나 조건을 바꿀 때. 같은 세션으로 이어진다
  const callAgent = useCallback(
    async (body: AgentRequest) => {
      setBusy(true);
      setNotice(null);
      try {
        const res = await fetch("/api/agent", {
          method: "POST",
          headers: { "Content-Type": "application/json", ...JSON.parse(headerKey) },
          body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error(ERRORS[res.status] ?? `요청이 실패했습니다 (${res.status})`);
        apply((await res.json()) as AgentResponse);
      } catch (e) {
        push({ role: "error", text: (e as Error).message });
      } finally {
        setBusy(false);
      }
    },
    [headerKey, apply, push],
  );

  const onSend = (input: ChatSend) => {
    push({ role: "user", text: input.text ?? "(캡처)", image: Boolean(input.image_base64) });
    void callAgent({
      session_id: sessionId,
      text: input.text,
      image_base64: input.image_base64,
      preset: input.preset,
      confirmed_participants: null,
    });
  };

  const recompute = () =>
    void callAgent({
      session_id: sessionId,
      text: "핀 위치 확인",
      image_base64: null,
      preset: null,
      confirmed_participants: pins.map((p) => ({ name: p.name, lng: p.lng, lat: p.lat })),
    });

  // 핀 하나를 옮기거나 자기 이름을 고를 때. 여기서는 다시 계산하지 않는다
  const patch = useCallback(
    async (body: ParticipantPatchRequest) => {
      setBusy(true);
      setNotice(null);
      try {
        const res = await fetch(`/api/session/${encodeURIComponent(sessionId)}/participants`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json", ...JSON.parse(headerKey) },
          body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error(ERRORS[res.status] ?? `저장하지 못했습니다 (${res.status})`);
        const data = (await res.json()) as ParticipantPatchResponse;
        setResponse((cur) => {
          if (!cur) return cur;
          const geocoded = (cur.geocoded ?? []).map((g) =>
            g.kind === "participant" && g.name === body.name && !body.claim
              ? { ...g, lng: body.lng, lat: body.lat, confidence: 1 }
              : g,
          );
          return { ...cur, slots: data.slots, result: data.result ?? cur.result, geocoded, edits: data.edits };
        });
        setNotice({
          kind: "ok",
          text: body.claim
            ? `${body.name} 님으로 등록했습니다. 지도에서 초록 핀이 내 핀입니다.`
            : "위치를 저장했습니다. 결과를 다시 계산하려면 아래 버튼을 누르세요.",
        });
      } catch (e) {
        setNotice({ kind: "error", text: (e as Error).message });
        setResponse((cur) => (cur ? { ...cur } : cur)); // 끌어 놓은 핀을 원래 자리로
      } finally {
        setBusy(false);
      }
    },
    [sessionId, headerKey],
  );

  const onMove = useCallback(
    (name: string, lng: number, lat: number) => {
      if (!pins.some((p) => p.name === name)) return;
      setMoved((m) => ({ ...m, [name]: [lng, lat] }));
      void patch({ name, lng, lat, claim: false });
    },
    [pins, patch],
  );

  const claim = (name: string) => {
    const pin = pins.find((p) => p.name === name);
    if (!pin) return;
    void patch({ name, lng: pin.lng, lat: pin.lat, claim: true });
  };

  if (notFound) {
    return (
      <div className="gate">
        <p>
          <strong>잘못된 경로입니다.</strong>
        </p>
        <p className="muted">없는 계획이거나 보관 기간이 지났습니다. 링크를 보낸 분께 다시 받아 주세요.</p>
        <Link href="/" className="primary-link">
          새 계획 만들기
        </Link>
      </div>
    );
  }
  if (loadError) return <div className="gate">{loadError}</div>;
  if (!response) return <div className="gate">불러오는 중…</div>;

  return (
    <div className="split">
      <div className="split-map">
        <MapView
          response={stage === "need_info" ? null : response}
          participantPins={pins}
          viewer={viewer}
          selectedRank={selectedRank}
          onSelectRank={setSelectedRank}
          onMove={onMove}
        />
      </div>
      <div className="split-side">
        <ShareBox sessionId={sessionId} />

        {stage === "done" && response.result && (
          <ResultTable
            result={response.result}
            participants={participants}
            selectedRank={selectedRank}
            onSelectRank={setSelectedRank}
          />
        )}

        <ChatPanel messages={messages} busy={busy} stage={stage ?? null} onSend={onSend}>
          {stage === "need_confirm" && (
            <div className="step">
              <p>
                <strong>위치가 맞나요?</strong> 주황 핀은 위치가 불확실합니다. 끌어서 고친 뒤 계산하세요.
              </p>
              <button type="button" className="primary" disabled={busy} onClick={recompute}>
                이 위치로 계산
              </button>
            </div>
          )}
          {stage === "done" && Object.keys(moved).length > 0 && (
            <div className="step">
              <p>핀 {Object.keys(moved).length}개가 바뀌었습니다.</p>
              <button type="button" className="primary" disabled={busy} onClick={recompute}>
                바뀐 위치로 다시 계산
              </button>
            </div>
          )}
          {stage === "failed" && (
            <div className="step">
              <button type="button" disabled={busy} onClick={recompute}>
                다시 시도
              </button>
            </div>
          )}
        </ChatPanel>

        <section className="claim">
          <h3>나는 누구인가요?</h3>
          {mine ? (
            <p>
              <strong>{mine.name}</strong> 님으로 등록돼 있습니다. 초록 핀이 내 핀입니다.
            </p>
          ) : (
            <p className="muted">
              자기 이름을 고르면 그 핀이 내 것으로 표시됩니다. 고르지 않아도 결과를 보고 핀을 옮길 수 있습니다.
            </p>
          )}
          <ul className="people">
            {participants.map((p) => {
              const hasPin = pins.some((x) => x.name === p.name);
              const state = p.owner_user_id === null ? "free" : p.owner_user_id === userId ? "me" : "taken";
              const edited = editedLabel((response.edits ?? []).find((e) => e.name === p.name), userId);
              return (
                <li key={p.name}>
                  <span>{p.name}</span>
                  <span className="muted">{p.origin ?? "출발지 미정"}</span>
                  {state === "me" && <span className="badge">나</span>}
                  {state === "taken" && <span className="badge badge-muted">다른 사람이 등록</span>}
                  {edited && <span className="muted edited">{edited}</span>}
                  {state === "free" && !mine && (
                    <button type="button" disabled={busy || !hasPin} onClick={() => claim(p.name)}>
                      이 사람이 나예요
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          {notice && <p className={notice.kind === "error" ? "error" : "ok"}>{notice.text}</p>}
        </section>

      </div>
    </div>
  );
}

function ShareBox({ sessionId }: { sessionId: string }) {
  const [copied, setCopied] = useState(false);
  const url = typeof window === "undefined" ? `/s/${sessionId}` : `${window.location.origin}/s/${sessionId}`;
  return (
    <section className="share">
      <h3>참석자에게 이 주소를 보내세요</h3>
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
        링크를 받은 사람은 구글 로그인 후 참석자 이름·출발지·집결지 위치를 보고, 자기 출발지를 고칠 수 있습니다.
      </p>
    </section>
  );
}
