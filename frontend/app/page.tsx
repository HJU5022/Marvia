"use client";

// 메인. 로그인하고, 무엇을 하는 서비스인지 읽고, 문장 하나를 넣는 곳이다.
// 지도는 여기에 없다. 계획이 만들어지면 /s/{id} 로 옮겨 가고, 그 주소가 참석자들이 모이는 자리다.
// 되묻기와 핀 확인도 거기서 한다 (09-20 화면 구조 결정).

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import AuthGate, { UserBar } from "@/components/AuthGate";
import { authHeaders, useAuth, type AuthState } from "@/lib/auth";
import type { AgentResponse, Preset } from "@/types/agent";

const EXAMPLES = [
  "목요일 아침 8시 진해 기지 레이더 정기점검. 저는 창원시청에서 차로, 최동료는 마산역에서 대중교통으로 옵니다. 출입조치는 신청했습니다.",
  "오늘 밤 10시 여의도 고객사 야간 배포. 저는 강남역에서 지하철, 윤업체는 판교역에서 지하철로 옵니다. 1층에서 인솔받습니다.",
];

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

export default function Home() {
  const auth = useAuth();
  return (
    <main className="app landing">
      <header className="topbar">
        <strong>Converge</strong>
        <span className="muted">현장 집결 장소·시각 정하기</span>
        <Link href="/my" className="topbar-link">
          내 계획
        </Link>
        <UserBar auth={auth} />
      </header>
      <AuthGate auth={auth} reason="Converge 는 구글 로그인 후 쓸 수 있습니다.">
        <Compose auth={auth} />
      </AuthGate>
    </main>
  );
}

function Compose({ auth }: { auth: AuthState }) {
  const router = useRouter();
  const headerKey = JSON.stringify(authHeaders(auth));
  const [text, setText] = useState("");
  const [preset, setPreset] = useState<Preset | "">("");
  const [image, setImage] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pickImage = (file: File | null) => {
    setError(null);
    if (!file) return setImage(null);
    if (!["image/png", "image/jpeg"].includes(file.type)) {
      setError("PNG 또는 JPG 캡처만 올릴 수 있습니다");
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setError("캡처가 5MB 를 넘습니다");
      return;
    }
    setImage(file);
  };

  const readBase64 = (file: File): Promise<string> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });

  const submit = async () => {
    const trimmed = text.trim();
    if (busy || (!trimmed && !image)) return;
    setBusy(true);
    setError(null);
    try {
      const image_base64 = image ? await readBase64(image) : null;
      const res = await fetch("/api/agent", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...JSON.parse(headerKey) },
        body: JSON.stringify({
          session_id: null,
          text: trimmed || null,
          image_base64,
          preset: preset || null,
          confirmed_participants: null,
        }),
      });
      if (res.status === 401) throw new Error("로그인이 만료됐습니다. 다시 로그인해 주세요.");
      if (!res.ok) throw new Error(`요청이 실패했습니다 (${res.status}). 잠시 후 다시 시도해 주세요.`);
      const data = (await res.json()) as AgentResponse;

      if (data.stage === "out_of_scope") {
        setError(data.message);
        return;
      }
      if (!data.session_id) {
        setError("계획을 만들지 못했습니다. 문장을 조금 더 자세히 적어 주세요.");
        return;
      }
      // 첫 응답을 넘겨 두면 다음 화면이 서버에 다시 묻지 않고 바로 그린다 (되묻기 문구 포함)
      try {
        sessionStorage.setItem(`converge:first:${data.session_id}`, JSON.stringify(data));
      } catch {
        // 저장이 막혀 있어도 /s/{id} 가 서버에서 다시 읽는다
      }
      router.push(`/s/${data.session_id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="landing-body">
      <section className="intro">
        <h1>모이는 자리와 시각을 문장 하나로 정합니다</h1>
        <p>
          함정 정비와 SI 야간 배포처럼 현장이 움직이는 일에서는 출입조치와 인솔 절차가 집결 장소를 가릅니다.
          Converge 는 그 절차까지 계산해 집결지와 참석자별 출발 시각을 냅니다.
        </p>
        <ol className="how">
          <li>
            <strong>문장을 넣습니다.</strong> 누가 어디서 무엇을 타고 오는지, 언제 어디서 하는 일인지
          </li>
          <li>
            <strong>링크가 만들어집니다.</strong> 그 주소를 단톡방에 전달합니다
          </li>
          <li>
            <strong>참석자들이 모입니다.</strong> 링크에서 각자 출발지를 고치고 결과를 함께 봅니다
          </li>
        </ol>
      </section>

      <section className="compose">
        <label className="compose-label" htmlFor="text">
          상황을 적어 주세요
        </label>
        <textarea
          id="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void submit();
            }
          }}
          rows={5}
          placeholder="예: 목요일 08:00 진해 기지 레이더 점검. 업체 두 분은 부산에서 차로 오세요"
        />

        <div className="compose-row">
          <select value={preset} onChange={(e) => setPreset(e.target.value as Preset | "")} aria-label="작업 종류">
            <option value="">작업 종류 자동</option>
            <option value="ship_maintenance">함정 정비</option>
            <option value="si_deploy">SI 배포·미팅</option>
          </select>
          <label className="file-btn">
            카톡 캡처 올리기
            <input type="file" accept="image/png,image/jpeg" onChange={(e) => pickImage(e.target.files?.[0] ?? null)} />
          </label>
          {image && (
            <button type="button" className="link" onClick={() => pickImage(null)}>
              {image.name} 빼기
            </button>
          )}
          <button
            type="button"
            className="primary"
            disabled={busy || (!text.trim() && !image)}
            onClick={() => void submit()}
          >
            {busy ? "만드는 중…" : "계획 만들기"}
          </button>
        </div>

        {busy && <p className="muted">문장을 읽고 위치를 찾는 중입니다. 10초쯤 걸립니다.</p>}
        {error && <p className="error">{error}</p>}

        <div className="examples">
          <span className="muted">이렇게 적어도 됩니다</span>
          {EXAMPLES.map((example) => (
            <button key={example} type="button" className="example" onClick={() => setText(example)}>
              {example}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
