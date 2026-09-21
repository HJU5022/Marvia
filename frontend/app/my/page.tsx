"use client";

// 내 계획 목록. 공유 링크 주소를 잃어버려도 자기 계획을 다시 찾는 입구다 (SDD 2절 GET /api/sessions).
// 참석자 이름은 여기 없다. 목록은 어깨너머로 보이기 쉬운 화면이라 필요한 것만 보여 준다 (테이블정의서 7절).

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import AuthGate, { UserBar } from "@/components/AuthGate";
import { authHeaders, useAuth, type AuthState } from "@/lib/auth";
import type { SessionBrief } from "@/types/agent";

const STATUS_LABEL: Record<string, string> = {
  draft: "작성 중",
  pins_confirmed: "위치 확인됨",
  computed: "계산 완료",
  failed: "실패",
};

const PRESET_LABEL: Record<string, string> = {
  ship_maintenance: "함정 정비",
  si_deploy: "SI 배포·미팅",
};

function when(iso: string): string {
  return new Date(iso).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" });
}

export default function MyPlansPage() {
  const auth = useAuth();
  return (
    <main className="app">
      <header className="topbar">
        <Link href="/" className="brand">
          Converge
        </Link>
        <span className="muted">내 계획</span>
        <UserBar auth={auth} />
      </header>
      <AuthGate auth={auth} reason="내 계획은 구글 로그인 후 볼 수 있습니다.">
        <Plans auth={auth} />
      </AuthGate>
    </main>
  );
}

function Plans({ auth }: { auth: AuthState }) {
  const headerKey = JSON.stringify(authHeaders(auth));
  const [rows, setRows] = useState<SessionBrief[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/sessions", { headers: JSON.parse(headerKey), cache: "no-store" });
      if (res.status === 401) throw new Error("로그인이 만료됐습니다. 다시 로그인해 주세요.");
      if (!res.ok) throw new Error(`목록을 불러오지 못했습니다 (${res.status})`);
      setRows((await res.json()) as SessionBrief[]);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [headerKey]);

  useEffect(() => {
    void load();
  }, [load]);

  const remove = async (row: SessionBrief) => {
    // 되돌릴 수 없는 삭제라 한 번 묻는다. 결과와 참석자 정보가 함께 지워진다
    const label = row.destination ?? row.purpose ?? "이 계획";
    if (!window.confirm(`${label} 계획을 지울까요? 결과와 참석자 정보가 함께 지워지고 되돌릴 수 없습니다.`)) {
      return;
    }
    setRemoving(row.id);
    setError(null);
    try {
      const res = await fetch(`/api/session/${encodeURIComponent(row.id)}`, {
        method: "DELETE",
        headers: JSON.parse(headerKey),
      });
      if (res.status === 403) throw new Error("본인이 만든 계획만 지울 수 있습니다.");
      if (!res.ok && res.status !== 204) throw new Error(`지우지 못했습니다 (${res.status})`);
      setRows((list) => (list ?? []).filter((x) => x.id !== row.id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRemoving(null);
    }
  };

  if (error && rows === null) return <div className="gate">{error}</div>;
  if (rows === null) return <div className="gate">불러오는 중…</div>;

  return (
    <div className="plans">
      <div className="plans-head">
        <h2>내 계획 {rows.length > 0 && <span className="muted">{rows.length}개</span>}</h2>
        <Link href="/" className="primary-link">
          새 계획 만들기
        </Link>
      </div>

      {error && <p className="error">{error}</p>}

      {rows.length === 0 ? (
        <div className="empty">
          <p>아직 만든 계획이 없습니다.</p>
          <p className="muted">첫 화면에서 문장을 넣으면 계획이 만들어지고 여기에 쌓입니다.</p>
        </div>
      ) : (
        <ul className="plan-list">
          {rows.map((row) => (
            <li key={row.id} className="plan">
              <Link href={`/s/${row.id}`} className="plan-main">
                <strong>{row.destination ?? "목적지 미정"}</strong>
                <span className="muted">{row.purpose ?? PRESET_LABEL[row.preset] ?? row.preset}</span>
                <span className="plan-meta">
                  참석자 {row.participant_count}명 · {STATUS_LABEL[row.status] ?? row.status} ·{" "}
                  {when(row.created_at)} 만듦
                  {row.meet_at ? ` · 약속 ${when(row.meet_at)}` : " · 시각 미정"}
                  {row.locked && " · 잠김"}
                </span>
              </Link>
              <button type="button" disabled={removing === row.id} onClick={() => void remove(row)}>
                {removing === row.id ? "지우는 중" : "삭제"}
              </button>
            </li>
          ))}
        </ul>
      )}

      <p className="muted note">
        만료된 계획은 목록에 나오지 않습니다. 약속이 있는 계획은 약속 뒤 30일, 시각이 없는 계획은 만든 뒤 7일까지
        보관합니다.
      </p>
    </div>
  );
}
