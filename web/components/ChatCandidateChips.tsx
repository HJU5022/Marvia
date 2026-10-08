'use client';
/** 채팅 답 말풍선 아래의 선박 후보 칩. "어느 배예요?"라고 되물은 답(insufficient)의 vessel_candidates를
 * 글로만 보이던 것을 눌러서 고를 수 있게 한다. 칩 하나는 배 이름 · 국적 · 목적지다.
 * 누르면 오른쪽 후보 고르기(CandidatePicker)와 똑같이 조회한다: 그 답의 요청에 resolved_mmsi만 더하고 후속 질문은 비운다 (SDD 4.3, C2).
 * 조회 중이거나 한도를 넘겼으면 누를 수 없다. 칩을 그릴지(가장 최근 되묻기 답인지, 아직 되묻는 중인지)는 ChatBar가 정한다. */
import {useApp} from './AppProvider';
import {WatchVesselButton} from './WatchVesselButton';
import {countryLabel, portLabel} from '@/lib/format';
import type {AgentResponse, AgentRequest} from '@/lib/types';

export function ChatCandidateChips({agent, request, disabled}: {agent: AgentResponse; request: AgentRequest; disabled: boolean}) {
  const {lookup} = useApp();
  return <div className="chat-cand-chips" role="group" aria-label="선박 후보 고르기">
    {/* 후보 배도 B/L 없이 지켜볼 수 있게 한다. 칩 안에 넣으면 버튼 속 버튼이라 칩 옆에 따로 둔다 (칩의 조회 클릭과 섞이지 않게) */}
    {agent.vessel_candidates.map(c => <div key={c.mmsi} className="chat-cand-item">
      <button type="button" className="chat-cand-chip" disabled={disabled}
        onClick={() => void lookup({...request, resolved_mmsi: c.mmsi, follow_up_question: null})}>
        <strong>{c.name}</strong><span>{countryLabel(c.flag)} · {c.dest ? portLabel(c.dest) : '목적지 확인 안 됨'}</span></button>
      <WatchVesselButton mmsi={c.mmsi} name={c.name} flag={c.flag} dest={c.dest}/>
    </div>)}
  </div>;
}
