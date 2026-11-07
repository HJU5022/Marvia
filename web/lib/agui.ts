// AG-UI 한 차례 부르기와 이벤트 모양 (설계 10절, 계획 4b Task 7).
// 서버(src/marvia/server.py)가 ag-ui-protocol로 보내는 SSE를 fetch 스트림으로 읽는다.
// [왜] @ag-ui/client는 rxjs·zod·proto를 끌어온다. 화면이 쓰는 이벤트는 일곱 가지라 직접 읽는다 (계획 4b 결정 D5).
// 하지 않는 일: 화면 그리기, 로그인(lib/auth.ts).

export type PlanItem = { content: string; status: "pending" | "in_progress" | "completed" };
export type Reading = { token: string; number: string; kind: string };
export type Cargo = {
  number: string;
  stage: string | null;
  stage_at: string | null;
  port: string | null;
  vessel: string | null;
  source: string | null;
  fetched_at: string | null;
  error: string | null;
};
export type EvidenceUnit = {
  unit_id: string;
  heading: string;
  effective: string;
  text: string;
  source_url: string | null;
};
export type View = { plan: PlanItem[]; reading: Reading[]; cargos: Cargo[]; evidence: EvidenceUnit[] };
export type ChoiceCard = {
  kind: "choice";
  question: string;
  options: { label: string; description: string }[];
  recommended: number;
  timeout_s: number;
};
export type ApprovalAction = {
  name: string;
  args: Record<string, unknown>;
  description: string;
  allowed: string[];
};
export type ApprovalCard = { kind: "approval"; actions: ApprovalAction[] };
export type Card = (ChoiceCard | ApprovalCard) & { id: string };

export type AgUiEvent =
  | { type: "RUN_STARTED"; threadId: string; runId: string }
  | { type: "STATE_SNAPSHOT"; snapshot: View }
  | { type: "TEXT_MESSAGE_START"; messageId: string }
  | { type: "TEXT_MESSAGE_CONTENT"; messageId: string; delta: string }
  | { type: "TEXT_MESSAGE_END"; messageId: string }
  | {
      type: "RUN_FINISHED";
      outcome?:
        | { type: "success" }
        | { type: "interrupt"; interrupts: { id: string; reason: string; metadata: ChoiceCard | ApprovalCard }[] };
    }
  | { type: "RUN_ERROR"; message: string; code?: string };

export const EMPTY_VIEW: View = { plan: [], reading: [], cargos: [], evidence: [] };

// [왜] crypto.randomUUID는 https·localhost에서만 있다. e2e 망(http://web-e2e)에서도 돌게 직접 만든다
export function newId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
}

type TurnInput = { threadId: string; text?: string; resume?: { interruptId: string; payload: unknown } };

// 한 차례를 보내고 이벤트마다 onEvent를 부른다. 서버가 거절하면(401·409·422) 상태 코드를 담아 던진다
export async function runTurn(
  apiUrl: string,
  token: string,
  input: TurnInput,
  onEvent: (event: AgUiEvent) => void,
): Promise<void> {
  // [주의] state·forwardedProps는 빈 값으로 보낸다. 서버도 읽지 않는다(계획 4b C7)
  const body = {
    threadId: input.threadId,
    runId: newId(),
    messages: input.text ? [{ id: newId(), role: "user", content: input.text }] : [],
    tools: [],
    context: [],
    state: {},
    forwardedProps: {},
    ...(input.resume
      ? { resume: [{ interruptId: input.resume.interruptId, status: "resolved", payload: input.resume.payload }] }
      : {}),
  };
  const response = await fetch(`${apiUrl}/agui`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream", authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    throw new Error(`서버가 요청을 받지 않았어요 (${response.status})`);
  }
  // SSE: "data: {json}" 줄들이 빈 줄로 나뉜다. 조각이 이벤트 중간에서 끊길 수 있어 버퍼에 모은다
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let end = buffer.indexOf("\n\n");
    while (end >= 0) {
      const chunk = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)) as AgUiEvent);
      }
      end = buffer.indexOf("\n\n");
    }
  }
}
