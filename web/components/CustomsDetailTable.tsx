/** UNI-PASS 처리 이력 원문 표 (docs/specs/customs-detail.md). 관세청이 준 값을 해석하지 않고 그대로 보여 준다.
 * 화면 전용 값이라 서버가 저장하지 않는다. 그래서 이력 재생이나 후속 질문 응답에는 없고, 그때는 표를 그리지 않는다.
 * React 텍스트로만 그려 안내문 속 글자가 HTML로 해석되지 않는다. */
import {FileText} from 'lucide-react';
import type {CustomsDetailRow} from '@/lib/types';
import {InfoTip} from './VerdictCard';

/** 20260915102707 → 2026.09.15 10:27 (UNI-PASS 처리 일시는 시간대 없이 한국 시각으로 온다) */
function stamp(v: string | null) {
  if (!v) return '-';
  const m = /^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})/.exec(v);
  return m ? `${m[1]}.${m[2]}.${m[3]} ${m[4]}:${m[5]}` : v;
}
function joined(a: string | null, b: string | null) { return [a, b].filter(Boolean).join(' ') || '-'; }

export function CustomsDetailTable({rows}: {rows: CustomsDetailRow[] | undefined}) {
  if (!rows?.length) return null;
  return <section className="customs-detail-section">
    <div className="fold-subhead"><h3 className="fold-sub">관세청 처리 내역<InfoTip label="관세청 처리 내역 설명">관세청 UNI-PASS가 알려 준 값을 그대로 보여 줘요. 이 내역은 저장하지 않아서 조회 이력에서는 다시 볼 수 없어요.</InfoTip></h3><FileText size={18}/></div>
    <div className="table-scroll" role="region" aria-label="관세청 처리 내역 표" tabIndex={0}>
      <table className="customs-detail-table">
        <thead><tr><th>처리 일시</th><th>처리 구분</th><th>장치장</th><th>반출입 일시</th><th>반출입 내용</th><th>신고번호</th><th>반출입 근거</th><th>포장</th><th>중량</th><th>안내</th></tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}>
          <td className="mono">{stamp(r.processed_at)}</td>
          <td><strong>{r.kind ?? '-'}</strong></td>
          <td title={r.shed_code ?? undefined}>{r.shed_name ?? '-'}</td>
          <td className="mono">{r.moved_at ?? '-'}</td>
          <td>{r.content ?? '-'}</td>
          <td className="mono">{r.declaration_no ?? '-'}</td>
          <td>{r.basis ?? '-'}</td>
          <td>{r.package_count && r.package_count !== '0' ? joined(r.package_count, r.package_unit) : '-'}</td>
          <td>{r.weight ? joined(r.weight, r.weight_unit) : '-'}</td>
          <td className="notice-cell">{r.notice ?? '-'}</td>
        </tr>)}</tbody>
      </table>
    </div>
  </section>;
}
