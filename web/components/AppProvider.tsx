'use client';
/** Shared session and last result. Responses never mutate the schema; SDD 4.3 and E3/E9. */
import {createContext, useContext, useRef, useState, type ReactNode} from 'react';
import {getAgentResponse, getPresentationData, getReplaySnapshot} from '@/lib/api';
import type {AgentRequest, AgentResponse} from '@/lib/types';
const presentation = getPresentationData();
interface AppState {
  data: typeof presentation; request: AgentRequest; result: AgentResponse | null;
  loading: boolean; stage: number; error: string; replaying: boolean;
  lookup: (req: AgentRequest) => Promise<boolean>; replay: (id: string) => boolean;
}
const Context = createContext<AppState | null>(null);
export function AppProvider({children}:{children:ReactNode}) {
  const [request,setRequest] = useState<AgentRequest>(presentation.demo.choices[0].request as AgentRequest);
  const [result,setResult] = useState<AgentResponse|null>(null);
  const [loading,setLoading] = useState(false); const [stage,setStage] = useState(0);
  const [error,setError] = useState(''); const [replaying,setReplaying] = useState(false);
  const inflight = useRef(false);
  async function lookup(req: AgentRequest) {
    if (inflight.current) return false;
    inflight.current = true; setLoading(true); setError(''); setStage(0); setReplaying(false);
    // These are simulated demo stages, not backend progress events.
    const a = setTimeout(()=>setStage(1),350); const b = setTimeout(()=>setStage(2),700);
    try { const response = await getAgentResponse(req); setResult(response); setRequest(req); return true; }
    catch (e) { setError(e instanceof Error ? e.message : '조회하지 못했습니다. 다시 시도해 주세요.'); return false; }
    finally {clearTimeout(a);clearTimeout(b);setLoading(false);inflight.current=false;}
  }
  function replay(id: string) {
    if (inflight.current) return false;
    const snapshot = getReplaySnapshot(id); if (!snapshot) return false;
    setResult(snapshot.response);setRequest(snapshot.request);setReplaying(true);setError('');return true;
  }
  return <Context.Provider value={{data:presentation,request,result,loading,stage,error,replaying,lookup,replay}}>{children}</Context.Provider>;
}
export function useApp() { const ctx=useContext(Context);if(!ctx)throw new Error('AppProvider is required');return ctx; }
