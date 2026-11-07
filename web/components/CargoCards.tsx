// 화물 카드 (설계 10절): 통관 단계, 항구, 단계 시각, 출처와 조회 시각.
// [왜] ETA·등급은 선박 위치 조회와 함께 2차로 미뤘다(계획 4b 결정 D3). 빈 칸 대신 그렇다고 적는다.
import type { Cargo } from "@/lib/agui";

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) : "모름";
}

export function CargoCards({ cargos }: { cargos: Cargo[] }) {
  if (!cargos.length) return null;
  return (
    <section aria-labelledby="cargo-title" className="panel">
      <h2 id="cargo-title">화물</h2>
      {cargos.map((c) => (
        <article key={c.number} className="cargo">
          <h3>{c.number}</h3>
          {c.error ? (
            <p>조회하지 못했어요: {c.error}</p>
          ) : (
            <dl>
              <dt>통관 단계</dt>
              <dd>{c.stage}</dd>
              <dt>항구</dt>
              <dd>{c.port ?? "모름"}</dd>
              <dt>단계 시각</dt>
              <dd>{when(c.stage_at)}</dd>
              <dt>ETA·등급</dt>
              <dd>선박 위치 조회 뒤(2차)</dd>
            </dl>
          )}
          <p className="meta">
            출처 {c.source ?? "모름"} · 조회 {when(c.fetched_at)}
          </p>
        </article>
      ))}
    </section>
  );
}
