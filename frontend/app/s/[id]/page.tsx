"use client";

// 공유 링크 화면. 로그인해야 결과가 보인다 (익명 열람 없음).
// 로그인한 참석자는 목록에서 자기를 골라(claim) 자기 핀을 옮길 수 있다. 고르지 않아도 결과는 본다 (SDD 7절).

import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import AuthGate, { UserBar } from "@/components/AuthGate";
import MapView from "@/components/MapView";
import { canEdit, pinsFrom, type Viewer } from "@/components/ParticipantPins";
import ResultTable from "@/components/ResultTable";
import { authHeaders, useAuth } from "@/lib/auth";
import type { AgentResponse, ParticipantPatchRequest, ParticipantPatchResponse } from "@/types/agent";

export default function SharePage() {
  const auth = useAuth();
  const { id } = useParams<{ id: string }>();
  return (
    <main className="app">
      <header className="topbar">
        <strong>Converge</strong>
        <span className="muted">공유된 집결 계획</span>
        <UserBar auth={auth} />
      </header>
      <AuthGate auth={auth} reason="공유된 집결 계획은 구글 로그인 후 볼 수 있습니다.">
        {auth.status === "signed_in" && (
          <Shared sessionId={id} userId={auth.userId} headers={authHeaders(auth)} />
        )}
      </AuthGate>
    </main>
  );
}

const PATCH_ERRORS: Record<number, string> = {
  401: "로그인이 만료됐습니다. 다시 로그인해 주세요.",
  403: "본인 핀만 수정할 수 있습니다",
  404: "세션이 없거나 만료됐습니다.",
  409: "이미 다른 사람이 등록했습니다",
};

function Shared({ sessionId, userId, headers }: { sessionId: string; userId: string; headers: Record<string, string> }) {
  const headerKey = JSON.stringify(headers);
  const [response, setResponse] = useState<AgentResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [selectedRank, setSelectedRank] = useState<number | null>(null);
  const viewer: Viewer = useMemo(() => ({ role: "participant", userId }), [userId]);

  useEffect(() => {
    let alive = true;
    fetch(`/api/session/${encodeURIComponent(sessionId)}`, { headers: JSON.parse(headerKey), cache: "no-store" })
      .then(async (res) => {
        if (!res.ok) throw new Error(PATCH_ERRORS[res.status] ?? `불러오지 못했습니다 (${res.status})`);
        return (await res.json()) as AgentResponse;
      })
      .then((data) => {
        if (!alive) return;
        setResponse(data);
        const first = data.result?.candidates
          .map((c) => c.rank)
          .filter((r): r is number => r !== null)
          .sort((a, b) => a - b)[0];
        setSelectedRank(first ?? null);
      })
      .catch((e: Error) => alive && setLoadError(e.message));
    return () => {
      alive = false;
    };
  }, [sessionId, headerKey]);

  const pins = useMemo(() => pinsFrom(response, {}), [response]);
  const participants = response?.slots?.participants ?? [];
  const mine = participants.find((p) => p.owner_user_id === userId) ?? null;

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
        if (!res.ok) throw new Error(PATCH_ERRORS[res.status] ?? `저장하지 못했습니다 (${res.status})`);
        const data = (await res.json()) as ParticipantPatchResponse;
        setResponse((cur) => {
          if (!cur) return cur;
          const geocoded = (cur.geocoded ?? []).map((g) =>
            g.kind === "participant" && g.name === body.name && !body.claim
              ? { ...g, lng: body.lng, lat: body.lat, confidence: 1 }
              : g,
          );
          return { ...cur, slots: data.slots, result: data.result ?? cur.result, geocoded };
        });
        setNotice({
          kind: "ok",
          text: body.claim
            ? `${body.name} 님으로 등록했습니다. 이제 내 핀을 끌어서 출발지를 고칠 수 있습니다.`
            : data.result
              ? "위치를 저장하고 다시 계산했습니다."
              : "위치를 저장했습니다. 다시 계산 중입니다.",
        });
      } catch (e) {
        setNotice({ kind: "error", text: (e as Error).message });
        // 지도에서 끌어 놓은 핀을 원래 자리로 돌린다
        setResponse((cur) => (cur ? { ...cur } : cur));
      } finally {
        setBusy(false);
      }
    },
    [sessionId, headerKey],
  );

  const onMove = useCallback(
    (name: string, lng: number, lat: number) => {
      const pin = pins.find((p) => p.name === name);
      if (!pin) return;
      if (!canEdit(viewer, pin.owner_user_id)) {
        setNotice({ kind: "error", text: "본인 핀만 수정할 수 있습니다" });
        return;
      }
      void patch({ name, lng, lat, claim: false });
    },
    [pins, viewer, patch],
  );

  const claim = (name: string) => {
    const pin = pins.find((p) => p.name === name);
    if (!pin) return;
    void patch({ name, lng: pin.lng, lat: pin.lat, claim: true });
  };

  if (loadError) return <div className="gate">{loadError}</div>;
  if (!response) return <div className="gate">불러오는 중…</div>;

  return (
    <div className="split">
      <div className="split-map">
        <MapView
          response={response}
          participantPins={pins}
          viewer={viewer}
          selectedRank={selectedRank}
          onSelectRank={setSelectedRank}
          onMove={onMove}
        />
      </div>
      <div className="split-side">
        <section className="step">
          <p>{response.message}</p>
          <p className="muted">
            로그인한 사람은 누구나 이 링크로 참석자 이름·출발지·집결지 위치를 볼 수 있습니다.
          </p>
        </section>

        <section className="claim">
          <h3>나는 누구인가요?</h3>
          {mine ? (
            <p>
              <strong>{mine.name}</strong> 님으로 등록돼 있습니다. 지도에서 파란 내 핀을 끌어 출발지를 고치세요.
            </p>
          ) : (
            <p className="muted">자기 이름을 고르면 그 핀을 직접 옮길 수 있습니다. 고르지 않아도 결과는 볼 수 있습니다.</p>
          )}
          <ul className="people">
            {participants.map((p) => {
              const hasPin = pins.some((x) => x.name === p.name);
              const state =
                p.owner_user_id === null ? "free" : p.owner_user_id === userId ? "me" : "taken";
              return (
                <li key={p.name}>
                  <span>{p.name}</span>
                  <span className="muted">{p.origin ?? "출발지 미정"}</span>
                  {state === "me" && <span className="badge">나</span>}
                  {state === "taken" && <span className="badge badge-muted">다른 사람이 등록</span>}
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

        {response.stage === "done" && response.result && (
          <ResultTable
            result={response.result}
            participants={participants}
            selectedRank={selectedRank}
            onSelectRank={setSelectedRank}
          />
        )}
        {response.stage === "failed" && <p className="error">경로 계산에 실패해 후보 위치만 표시합니다.</p>}
      </div>
    </div>
  );
}
