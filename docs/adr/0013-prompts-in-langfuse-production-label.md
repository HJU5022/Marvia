# 0013. 프롬프트는 Langfuse에서 이름으로 가져오고 production 라벨로 되돌린다

상태: 채택

## 맥락
프롬프트를 코드에 문자열로 두면 바꿀 때마다 배포해야 하고 버전 추적이 어렵다. 프롬프트는 10개다 (`backend/app/prompts/`).

## 결정
- 코드에 프롬프트 문자열을 두지 않는다. `observability/langfuse.get_prompt(name, label="production")`로 가져온다.
- 10개 모두 Langfuse에 등록한다 ([docs/evidence/langfuse_summary.md](../evidence/langfuse_summary.md) Prompt Management 표, [release_manifest.json](../release_manifest.json) `prompts`). Langfuse 키가 없거나 가져오기가 실패하면 레포 파일 `backend/app/prompts/<이름>.md`를 쓴다. 이때 트레이스의 prompt_version은 `local`이다.
- 호출마다 트레이스에 prompt_version을 남긴다.
- 되돌리기는 production 라벨을 이전 version에 붙이는 것이다. 서비스는 약 60초 캐시 뒤 새 버전을 읽는다.
- 버전별로 무엇을 왜 바꿨고 결과가 어땠는지는 [prompt_versions.md](../prompt_versions.md)에, 현재 production 번호와 되돌릴 번호는 [release_manifest.json](../release_manifest.json)에 적는다.

## 결과
- 좋아진 것: 판정 프롬프트 5를 production에서 4로 실제로 되돌렸다 ([EVAL_REPORT 4절](../../EVAL_REPORT.md) 표 2번, DISCARD).
- 대가: 레포 파일과 Langfuse 등록본이 같은지 따로 확인해야 한다. 처음엔 Langfuse에서 먼저 고치고 레포 파일에 복사했다 ([prompt_versions.md](../prompt_versions.md) 머리말). 지금 순서는 [0014](0014-prompt-release-order.md)다.

## 근거
- [SDD](../Marvia_SDD.md) 5.6절, 6.4절
- [release_manifest.json](../release_manifest.json) `prompts`, `rollback`, [prompt_versions.md](../prompt_versions.md)
- [CLAUDE.md](../../CLAUDE.md) "하지 말 것": "프롬프트를 코드에 문자열로 두지 않는다", "프롬프트 배포 순서" 절
