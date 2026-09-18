"use client";

// 지금 어디까지 왔는지 보여 준다. 파이프라인 단계(SDD 5절)를 사용자 말로 묶은 것이다.
// 응답이 20초 넘게 걸리기도 해서, 무엇을 기다리는지 보이지 않으면 멈춘 것처럼 느껴진다 (가이드 8-3 즉각 피드백).

import type { Stage } from "@/types/agent";

// 화면에 보여줄 단계. 괄호 안은 대응하는 파이프라인 단계다
const STEPS = [
  { key: "read", label: "말 읽기" }, // 0 vision, 1 extract
  { key: "locate", label: "위치 찾기" }, // 2 geocode
  { key: "gather", label: "집결 후보" }, // 3 candidates
  { key: "route", label: "경로·시각" }, // 4~7 routes, rules, judge, departure
] as const;

type StepKey = (typeof STEPS)[number]["key"];

// stage 별로 "여기까지 끝났다"고 볼 수 있는 자리 (SDD 2절)
const DONE_UNTIL: Record<Stage, StepKey | null> = {
  need_info: "read", // 읽었고, 되물을 것이 생겼다
  need_confirm: "locate", // 위치까지 찾았고, 확인을 기다린다
  done: "route",
  out_of_scope: "read",
  failed: null, // 어디서 끊겼는지 모른다. 회색으로 둔다
};

interface Props {
  busy: boolean;
  stage: Stage | null;
}

export default function Progress({ busy, stage }: Props) {
  if (!busy && stage === null) return null;

  const doneUntil = stage ? DONE_UNTIL[stage] : null;
  const doneIndex = doneUntil ? STEPS.findIndex((s) => s.key === doneUntil) : -1;
  // 계산 중이면 끝난 단계 다음 칸이 진행 중이다
  const activeIndex = busy ? Math.min(doneIndex + 1, STEPS.length - 1) : -1;

  return (
    <ol className="progress" aria-label="진행 단계">
      {STEPS.map((step, i) => {
        const state = i <= doneIndex ? "done" : i === activeIndex ? "active" : "todo";
        return (
          <li key={step.key} className={`progress-step ${state}`}>
            <span className="progress-dot" aria-hidden="true" />
            {step.label}
          </li>
        );
      })}
    </ol>
  );
}
