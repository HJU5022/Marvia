// 화물 카드 (설계 10절): 통관 단계, 항구, 단계 시각, 출처와 조회 시각.
// [왜] ETA·등급은 선박 위치 조회와 함께 2차로 미뤘다(계획 4b 결정 D3). 빈 칸 대신 그렇다고 적는다.
// 서버의 배 식별 스위치가 켜져 있으면(verdict 칸이 오면) 그 자리에 배와 판정 칸을 보인다 (계획 8b).
// [주의] 등급·일정·확신과 그 까닭은 서버가 보낸 글 그대로다. 화면이 등급을 정하거나 바꾸지 않는다.
import type { Cargo } from "@/lib/agui";

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) : "모름";
}

function VesselCells({ c }: { c: Cargo }) {
  const ship = c.ship;
  const v = c.verdict;
  const why = v ? [...v.signals, ...v.notes, ...v.info] : [];
  return (
    <>
      <dt>배</dt>
      <dd>
        {ship?.name ?? "확인하지 못함"}
        {ship?.mmsi ? ` (호출부호 ${ship.call_sign ?? "없음"} · 배 번호 ${ship.mmsi})` : ""}
        {ship ? <span className="hint">{ship.reason}</span> : null}
        {ship?.detail ? <span className="hint">{ship.detail}</span> : null}
        {ship?.check ? <span className="hint">서류로 본 결과: {ship.check}</span> : null}
      </dd>
      {v ? (
        <>
          <dt>등급</dt>
          <dd data-grade={v.grade ?? "none"}>{v.grade_label}</dd>
          <dt>일정</dt>
          <dd>{v.schedule}</dd>
          <dt>확신</dt>
          <dd>{v.confidence}</dd>
          <dt>도착 예정</dt>
          <dd>{v.eta ? `${when(v.eta)} (${v.eta_source ?? "출처 모름"})` : "모름"}</dd>
          {why.length ? (
            <>
              <dt>까닭</dt>
              <dd>
                <ul>
                  {why.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </dd>
            </>
          ) : null}
        </>
      ) : ship?.status === "ask" ? (
        <>
          <dt>등급</dt>
          <dd>배를 확인한 뒤에 보여 드려요</dd>
        </>
      ) : null}
    </>
  );
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
              {c.verdict === undefined ? (
                <>
                  <dt>ETA·등급</dt>
                  <dd>선박 위치 조회 뒤(2차)</dd>
                </>
              ) : (
                <VesselCells c={c} />
              )}
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
