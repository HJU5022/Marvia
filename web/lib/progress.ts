/** 답을 기다리는 동안 보여 줄 서버의 실제 처리 단계 (docs/specs/chat-progress.md).
 * 단계 이름은 backend/app/services/progress.py STAGES와 같다. 여기 없는 이름은 화면에 보이지 않는다.
 * 화면은 서버가 보낸 단계만 그린다. 타이머로 단계를 넘기거나 퍼센트를 만들지 않는다 (가이드 8-3).
 */
export type ProgressStage = 'understand' | 'customs' | 'identify' | 'position' | 'judge' | 'answer' | 'schedule' | 'ports'
  | 'tool_candidates' | 'tool_position' | 'tool_schedule' | 'tool_distance' | 'memory';

export const stageLabels: Record<ProgressStage, string> = {
  understand: '질문 이해',
  customs: '통관 정보 조회',
  identify: '선박 식별',
  position: '위치·입항 일정 확인',
  judge: '판정 정리와 검증',
  answer: '답변 작성과 검증',
  schedule: '부산 입항 예정 조회',
  ports: '지역 항구 찾기',
  // 에이전트가 읽기 전용 조회 도구를 부를 때 서버가 보내는 단계 (도구 하나에 이름 하나)
  tool_candidates: '선박 후보 찾기',
  tool_position: '선박 실시간 위치 조회',
  tool_schedule: '부산 입항 기록 조회',
  tool_distance: '남은 항로 거리 계산',
  // 기억 뽑기가 저장할 내용을 찾았을 때만 서버가 보낸다 (거래처·선호·일정 등 모든 메모 종류에 맞는 말)
  memory: '메모 저장 중',
};

export function isStage(value: unknown): value is ProgressStage {
  return typeof value === 'string' && value in stageLabels;
}

/** SSE 이벤트 하나 (HTML Living Standard, Server-sent events). data는 서버가 보낸 JSON 한 줄이다 */
export interface SseEvent { event: string; data: string }

/** 받은 글자 조각을 쌓아 두었다가 빈 줄로 끝난 이벤트만 꺼낸다.
 * 네트워크 조각은 이벤트 경계와 상관없이 잘려 오므로, 끝나지 않은 마지막 덩어리는 다음 조각을 기다린다.
 * 콜론으로 시작하는 줄(: ping)은 연결 유지용 주석이라 버린다. */
export function createSseParser() {
  let buffer = '';
  return function push(chunk: string): SseEvent[] {
    buffer += chunk.replace(/\r\n/g, '\n');
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() ?? '';
    const events: SseEvent[] = [];
    for (const block of blocks) {
      let event = 'message';
      const data: string[] = [];
      for (const line of block.split('\n')) {
        if (!line || line.startsWith(':')) continue;
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
      }
      if (data.length) events.push({event, data: data.join('\n')});
    }
    return events;
  };
}
