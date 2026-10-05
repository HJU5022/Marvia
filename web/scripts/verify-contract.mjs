/** Check local fixtures against a read-only AST snapshot of the actual Python contracts.
 * Also exercise replay context and date mismatch so fixed snapshots cannot mislead users.
 * No Python runtime, environment, original repository or external API is needed.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import Module from 'node:module';
import ts from 'typescript';
const root=process.cwd();
const {definitions}=JSON.parse(fs.readFileSync('scripts/backend-contract.json','utf8'));
function validate(value,schema,at){
 if(schema.ref)return validate(value,definitions[schema.ref],at);
 if(schema.anyOf){for(const s of schema.anyOf){try{validate(value,s,at);return;}catch{}}throw new Error(`${at}: no union member matches`);}
 if(schema.enum){assert(schema.enum.includes(value),`${at}: invalid enum ${value}`);return;}
 if(schema.type==='null'){assert.equal(value,null,at);return;}
 if(schema.type==='array'){assert(Array.isArray(value),at);value.forEach((v,i)=>validate(v,schema.items,`${at}[${i}]`));return;}
 if(schema.type==='object'){assert(value&&typeof value==='object'&&!Array.isArray(value),at);if(schema.properties){assert.deepEqual(Object.keys(value).sort(),schema.required.slice().sort(),`${at}: exact fields`);for(const [key,s] of Object.entries(schema.properties))validate(value[key],s,`${at}.${key}`);}return;}
 assert.equal(typeof value,schema.type==='integer'?'number':schema.type,at);
 if(schema.type==='integer')assert(Number.isInteger(value),at);
 if(schema.format)assert(!Number.isNaN(Date.parse(value)),`${at}: date format`);
}
for(const id of ['ok','partial','insufficient','failed','unsupported','watch','act']){
 const r=JSON.parse(fs.readFileSync(`lib/fixtures/${id}.json`,'utf8'));validate(r,definitions.AgentResponse,id);
 if(r.status==='insufficient'){assert.equal(r.verdict,null);assert(r.missing_inputs.length||r.vessel_candidates.length);}
 if(r.verdict==='watch'||r.verdict==='act')assert(r.reasons.some(s=>s.triggered));
 if(r.days_margin!==null)assert(r.evidence.some(e=>e.field==='days_margin'&&Number(e.value)===r.days_margin));
}
validate(JSON.parse(fs.readFileSync('lib/fixtures/history.json','utf8')),definitions.HistoryResponse,'history');
// 서류 사진 응답과 화물 비서 기억 (10-02, schemas/document.py · schemas/memory.py). 칸이 하나라도 다르면 실패한다
const documentFixture=JSON.parse(fs.readFileSync('lib/fixtures/document.json','utf8'));validate(documentFixture,definitions.DocumentResponse,'document');
const memoryFixture=JSON.parse(fs.readFileSync('lib/fixtures/memory.json','utf8'));validate(memoryFixture,definitions.MemoryResponse,'memory');
// 화면에 가는 기억에는 가린 번호만 있다. 가리지 않은 예시 B/L(MRVDEMO + 숫자)이 섞이면 안 된다 (SDD 3.5)
assert(!/MRVDEMO\d{4}/.test(JSON.stringify(memoryFixture)),'memory fixture must not contain an unmasked B/L');
assert.equal(new Set(memoryFixture.items.map(i=>i.id)).size,memoryFixture.items.length,'memory item ids must be unique');
// In-memory transpilation runs exactly lib/api.ts; it does not create duplicate test code.
// api.ts가 다른 .ts(lib/auth.ts)를 불러도 같은 방식으로 옮겨 읽게 한다 (10-01, 로그인 추가)
const tsOptions={compilerOptions:{module:ts.ModuleKind.CommonJS,esModuleInterop:true,target:ts.ScriptTarget.ES2022}};
Module._extensions['.ts']=(m,f)=>m._compile(ts.transpileModule(fs.readFileSync(f,'utf8'),tsOptions).outputText,f);
const filename=path.join(root,'lib/api.ts');
const compiled=ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,esModuleInterop:true,target:ts.ScriptTarget.ES2022}}).outputText;
const mod=new Module(filename);mod.filename=filename;mod.paths=Module._nodeModulePaths(path.dirname(filename));mod._compile(compiled,filename);
const api=mod.exports;process.env.NODE_ENV='development';const {demo}=api.getPresentationData();
const req=id=>structuredClone(demo.choices.find(c=>c.id===id).request);
api.selectFixture('partial');assert.equal((await api.getAgentResponse(req('partial'))).status,'partial');
const replay=api.getReplaySnapshot('fixture-failed-20261020');assert(replay);assert.equal((await api.getAgentResponse(replay.request)).status,'failed');
api.getReplaySnapshot('fixture-ok-20261020');const followup=await api.getAgentResponse({...req('ok'),follow_up_question:'근거는?'});assert.equal(followup.status,'ok');assert(followup.evidence.length>0);
await assert.rejects(()=>api.getAgentResponse({...req('ok'),sale_due_date:'2026-10-01'}),/저장된 예시와 조회 조건/);
await assert.rejects(()=>api.getAgentResponse({...req('ok'),bl_type:'HOUSE'}),/저장된 예시와 조회 조건/);
assert.deepEqual(await api.getHistory('different-session'),{items:[],available:true});
const candidates=JSON.parse(fs.readFileSync('lib/fixtures/insufficient.json','utf8')).vessel_candidates;
assert.equal((await api.getAgentResponse({...req('insufficient'),resolved_mmsi:candidates[0].mmsi})).status,'ok');
assert.equal((await api.getAgentResponse({...req('insufficient'),resolved_mmsi:candidates[1].mmsi,voyage_no:'EXAMPLE'})).status,'insufficient');
// 처리 단계 소식 (docs/specs/chat-progress.md, 10-02). lib/progress.ts를 그대로 옮겨 실행한다
const progressFile=path.join(root,'lib/progress.ts');
const pm=new Module(progressFile);pm.filename=progressFile;pm._compile(ts.transpileModule(fs.readFileSync(progressFile,'utf8'),tsOptions).outputText,progressFile);
const {createSseParser,isStage,stageLabels}=pm.exports;
// 네트워크 조각은 이벤트 중간에서 잘려 온다. 끝난 이벤트만 꺼내고, 주석 줄(: ping)과 CRLF 줄바꿈도 견딘다
const push=createSseParser();
assert.deepEqual(push('event: progress\ndata: {"stage":"cus'),[]);
assert.deepEqual(push('toms"}\n\n: ping\n\nevent: result\r\ndata: {"kind":"message"}\r\n\r\n'),[{event:'progress',data:'{"stage":"customs"}'},{event:'result',data:'{"kind":"message"}'}]);
assert(isStage('judge')&&!isStage('made-up'));
// 화면 라벨과 서버 단계 이름이 같아야 한다. 한쪽에만 있으면 화면이 단계를 버리거나 서버가 못 보낸다
const backendStages=[...fs.readFileSync(path.join(root,'../backend/app/services/progress.py'),'utf8').match(/STAGES = \(([\s\S]*?)\n\)/)[1].matchAll(/"([a-z_]+)"/g)].map(m=>m[1]);
assert.deepEqual(Object.keys(stageLabels).sort(),backendStages.slice().sort(),'progress stage names differ between web and backend');
// B/L 2~3개 비교 표 (ChatCargoTable, 10-05). 줄의 칸 이름이 서버 ChatCargo와 같아야 하고, 여유 일수 문구는 VerdictCard와 같은 말이다
const chatSrc=fs.readFileSync(path.join(root,'../backend/app/routers/chat.py'),'utf8');
const backendCargo=[...chatSrc.match(/class ChatCargo\(BaseModel\):[\s\S]*?\n\n\nclass/)[0].matchAll(/^    ([a-z_]+): /gm)].map(m=>m[1]);
const webCargo=[...fs.readFileSync(path.join(root,'lib/types.ts'),'utf8').match(/export interface ChatCargo \{([\s\S]*?)\n\}/)[1].matchAll(/\b([a-z_]+)\??:/g)].map(m=>m[1]);
assert.deepEqual([...new Set(webCargo)].sort(),backendCargo.slice().sort(),'ChatCargo fields differ between web and backend');
assert(/cargos: list\[ChatCargo\] = \[\]/.test(chatSrc),'ChatResponse.cargos must default to an empty list');
const fmtFile=path.join(root,'lib/format.ts');
const fm=new Module(fmtFile);fm.filename=fmtFile;fm.paths=Module._nodeModulePaths(path.dirname(fmtFile));fm._compile(ts.transpileModule(fs.readFileSync(fmtFile,'utf8'),tsOptions).outputText,fmtFile);
const {marginText}=fm.exports;
assert.equal(marginText({days_margin:3,sale_due_date:'2026-10-11'}),'3일 여유');
assert.equal(marginText({days_margin:-2,sale_due_date:'2026-10-11'}),'2일 늦음');
assert.equal(marginText({days_margin:0,sale_due_date:'2026-10-11'}),'0일 여유');
assert.equal(marginText({days_margin:null,sale_due_date:'2026-10-11'}),'미확인');
assert.equal(marginText({days_margin:null,sale_due_date:null}),'판매일 없음');
// 로그인 뒤 돌아올 주소에 #이 남으면 ##access_token이 되어 supabase-js가 출입증을 못 읽는다 (lib/auth.ts returnAddress, 10-02)
const authFile=path.join(root,'lib/auth.ts');
const am=new Module(authFile);am.filename=authFile;am.paths=Module._nodeModulePaths(path.dirname(authFile));am._compile(ts.transpileModule(fs.readFileSync(authFile,'utf8'),tsOptions).outputText,authFile);
const {parseParametersFromURL}=Module.createRequire(authFile)('@supabase/auth-js/dist/main/lib/helpers.js');
for(const href of ['http://localhost:3000/settings#','http://localhost:3000/?fixture=ok#evidence','http://localhost:3000/history']){
 const u=new URL(href);const back=am.exports.returnAddress(u);
 assert(!back.includes('#'),`return address keeps #: ${back}`);
 assert.equal(parseParametersFromURL(`${back}#access_token=T&refresh_token=R`).access_token,'T','supabase-js must read the token');
}
console.log('PASS: 7 AgentResponse fixtures, history envelope, document and memory fixtures, null/enums/evidence, replay isolation, date/type mismatch, candidate resolution, session isolation, SSE parsing, stage names, chat cargo table fields and login return address.');
