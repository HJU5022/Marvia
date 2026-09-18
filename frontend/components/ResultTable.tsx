"use client";

// done 결과 표. 집결 후보(순위·근거)와 선택한 후보 기준 참석자별 출발 시각·소요시간·여유·첫차.

import type { Participant, Result } from "@/types/agent";
import { CANDIDATE_STYLES } from "./MapView";
import { ROUTE_STYLES } from "./RouteLines";

interface Props {
  result: Result;
  participants: Participant[];
  selectedRank: number | null;
  onSelectRank: (rank: number) => void;
}

function basis(p: Participant | undefined, viaPickup: boolean, viaRendezvous: boolean): string {
  if (viaPickup && p?.pickup) return `${p.pickup} 님 차로 ${p.pickup_at ?? "픽업 지점"}에서 탑승`;
  if (viaRendezvous) return "집결지를 거쳐 이동";
  return "출발지에서 바로 이동";
}

export default function ResultTable({ result, participants, selectedRank, onSelectRank }: Props) {
  const ranked = [...result.candidates].sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
  const current = result.candidates.find((c) => c.rank === selectedRank) ?? null;
  const rows = result.per_participant.filter((r) => r.candidate_rank === selectedRank);

  return (
    <section className="result">
      {result.provisional && <div className="badge badge-warn">시각 미확정, 잠정</div>}

      <h3>집결 후보</h3>
      <ol className="candidates">
        {ranked.map((c) => (
          <li key={c.name}>
            <button
              type="button"
              className={`cand ${c.rank === selectedRank ? "active" : ""}`}
              disabled={c.rank === null}
              onClick={() => c.rank !== null && onSelectRank(c.rank)}
            >
              <span className="cand-rank" style={{ background: CANDIDATE_STYLES[c.kind].fill }}>
                {c.rank ?? "-"}
              </span>
              <span className="cand-body">
                <strong>{c.name}</strong>
                <span className="muted">
                  {" "}
                  {CANDIDATE_STYLES[c.kind].label}
                  {c.access_ok ? "" : " · 현재 출입조치로 불가"}
                </span>
                {c.switched_from && <span className="muted"> · {c.switched_from}에서 전환</span>}
                <span className="reason">{c.reason}</span>
                {c.rejected_reason && <span className="reason muted">제외·후순위 이유: {c.rejected_reason}</span>}
              </span>
            </button>
          </li>
        ))}
      </ol>

      {current && rows.length > 0 && (
        <>
          <h3>
            {current.name} 기준 출발 시각
            {result.rendezvous_departure && (
              <span className="muted"> · 집결지 출발 {result.rendezvous_departure}</span>
            )}
          </h3>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>참석자</th>
                  <th>이동</th>
                  <th>출발</th>
                  <th>소요</th>
                  <th>여유</th>
                  <th>도착 기한</th>
                  <th>첫차·막차</th>
                  <th>근거</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const p = participants.find((x) => x.name === r.name);
                  return (
                    <tr key={r.name}>
                      <td>{r.name}</td>
                      <td>
                        <span className="dot" style={{ background: ROUTE_STYLES[r.transport].color }} />
                        {ROUTE_STYLES[r.transport].label}
                        {r.transfer_count !== null && r.transport === "transit" && ` · 환승 ${r.transfer_count}`}
                      </td>
                      <td className="strong">{r.departure_time}</td>
                      <td>
                        {r.duration_min}분 <span className="muted">(경로 {r.raw_duration_min}분)</span>
                      </td>
                      <td>{r.buffer_min}분</td>
                      <td>{r.arrive_by}</td>
                      <td>{r.first_train || r.last_train ? `${r.first_train ?? "-"} / ${r.last_train ?? "-"}` : "-"}</td>
                      <td>{basis(p, r.via_pickup, r.via_rendezvous)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
      {current && rows.length === 0 && <p className="muted">이 후보에 대한 참석자별 계산이 없습니다.</p>}
    </section>
  );
}
