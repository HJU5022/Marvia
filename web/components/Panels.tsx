// 계획 진행, "이렇게 읽었어요", 근거 패널 (설계 10절). 값은 글자로만 그린다(dangerouslySetInnerHTML 쓰지 않음).
import { BookOpen, ExternalLink, ListChecks, ScanText } from "lucide-react";

import type { EvidenceUnit, PlanItem, Reading } from "@/lib/agui";

const STATUS: Record<PlanItem["status"], string> = { pending: "대기", in_progress: "진행 중", completed: "끝" };

export function PlanList({ plan }: { plan: PlanItem[] }) {
  if (!plan.length) return null;
  return (
    <section aria-labelledby="plan-title">
      <h2 id="plan-title" className="section-title">
        <ListChecks size={16} aria-hidden="true" />
        계획
      </h2>
      <ol className="plan">
        {plan.map((item, i) => (
          <li key={i} data-status={item.status}>
            <span className="badge">{STATUS[item.status]}</span> {item.content}
          </li>
        ))}
      </ol>
    </section>
  );
}

export function ReadingList({ reading }: { reading: Reading[] }) {
  if (!reading.length) return null;
  return (
    <section aria-labelledby="reading-title">
      <h2 id="reading-title" className="section-title">
        <ScanText size={16} aria-hidden="true" />
        이렇게 읽었어요
      </h2>
      <ul className="reading">
        {reading.map((r) => (
          <li key={r.token}>
            <span className="kind">{r.kind}</span> <strong>{r.number}</strong>
          </li>
        ))}
      </ul>
    </section>
  );
}

// [주의] 링크는 국가법령정보센터(https)만 만든다. 서버도 거르지만 화면에서 한 번 더 본다(javascript: 링크 막기)
function safeLink(url: string | null): string | null {
  return url && url.startsWith("https://www.law.go.kr/") ? url : null;
}

export function EvidencePanel({ evidence }: { evidence: EvidenceUnit[] }) {
  if (!evidence.length) return null;
  return (
    <section aria-labelledby="evidence-title">
      <h2 id="evidence-title" className="section-title">
        <BookOpen size={16} aria-hidden="true" />
        근거
      </h2>
      {evidence.map((e) => {
        const link = safeLink(e.source_url);
        return (
          <article key={e.unit_id} className="evidence">
            <h3>{e.heading}</h3>
            <p className="meta">
              시행일 {e.effective} · {e.unit_id}
            </p>
            <p className="text">{e.text}</p>
            {link ? (
              <a href={link} target="_blank" rel="noopener noreferrer">
                원문 보기 (국가법령정보센터)
                <ExternalLink size={14} aria-hidden="true" />
              </a>
            ) : null}
          </article>
        );
      })}
    </section>
  );
}
