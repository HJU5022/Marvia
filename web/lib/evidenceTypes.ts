/** 답 문장 속 근거 표시와 대화 근거 모음의 타입.
 * 서버(backend/app/services/citations.py)가 만든 값을 그대로 받는다. types.ts는 다른 작업이 고치는 중이라 따로 둔다. */

/** 근거 한 묶음. 같은 출처·같은 조회 시각의 값들이 한 개로 온다 */
export interface EvidenceItem {
  id: string;                       // "E1" 같은 짧은 id. 답 문장의 [E1]이 가리킨다
  source: 'unipass' | 'shipfinder' | 'mof' | 'searoute' | 'rule' | 'web' | string;
  fetched_at: string;               // ISO 시각. 모르면 빈 글자
  values: {field: string; value: string}[];
  url?: string;                     // 웹 결과만. http(s)만 온다
  title?: string;                   // 웹 결과만
}

/** 답 글 속 표시 한 개. start/end는 text 안 "[E1]"의 위치. 어긋나면 화면이 글자를 다시 찾는다 */
export interface Citation {
  id: string;
  start: number;
  end: number;
  evidence_ref: string;
}

/** 대화 근거 모음 한 줄. 같은 출처·항목·값은 한 번만 나온다 */
export interface ConversationEvidenceEntry extends EvidenceItem {
  turn?: number;                    // 몇 번째 답에서 나왔나(최신이 큼). 없으면 배열 순서를 따른다
}

// 사용자에게 보이는 출처 이름 (결정 1). lib/format.ts의 sourceLabels와 달리 짧은 이름이다
export const citationSourceLabels: Record<string, string> = {
  unipass: '관세청 UNI-PASS', shipfinder: '선박 위치 AIS', mof: '해수부', searoute: '해상 거리 계산', rule: 'Marvia 계산', web: '웹',
};
export function citationSourceLabel(source: string) { return citationSourceLabels[source] ?? '기타 출처'; }
