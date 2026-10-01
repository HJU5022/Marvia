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
console.log('PASS: 7 AgentResponse fixtures, history envelope, null/enums/evidence, replay isolation, date/type mismatch, candidate resolution and session isolation.');
