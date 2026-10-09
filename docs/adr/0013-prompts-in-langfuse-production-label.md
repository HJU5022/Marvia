# 0013. 프롬프트는 Langfuse에서 이름으로 가져오고 production 라벨로 되돌린다

상태: 채택

## 맥락
프롬프트를 코드에 문자열로 두면 바꿀 때마다 배포해야 하고 버전 추적이 어렵다. 개발 중에는 프롬프트 5종이었고 지금은 10종이다 (작업 리스트 C-11).

## 결정
- 코드에 프롬프트 문자열을 두지 않는다. `observability/langfuse.get_prompt(name, label="production")`로 가져온다.
- Langfuse 키가 없거나 실패하면 `backend/app/prompts/<이름>.md` 로컬 사본을 쓴다(트레이스의 prompt_version은 "local"). `marvia-memory-write`는 Langfuse에 등록하지 않고 레포 파일로 동작한다.
- 호출마다 트레이스에 prompt_version을 남긴다.
- 되돌리기는 production 라벨을 이전 version에 붙이는 것이다. 서비스는 약 60초 캐시 뒤 새 버전을 읽는다.
- 버전별 무엇을 왜 바꿨고 결과가 어땠는지는 `docs/prompt_versions.md`에, 현재 번호와 되돌릴 번호는 `docs/release_manifest.json`에 적는다.

## 대안
근거 문서에 비교한 대안이 적혀 있지 않다.

## 결과
좋아진 것: 실제로 판정 프롬프트 5번을 production에서 4로 되돌렸다 (`EVAL_REPORT.md` 4절 2번 DISCARD). 대가: 레포 파일과 Langfuse 등록본이 같은지 직접 확인해야 한다. 처음엔 Langfuse에서 먼저 고치고 레포 파일에 복사했다(`docs/prompt_versions.md` 머리말). 지금 순서는 ADR 0014다.

## 근거
- `docs/Marvia_SDD.md` 5.6절, 6.4절
- `docs/release_manifest.json` rollback, `docs/prompt_versions.md`
- `CLAUDE.md` "하지 말 것" 3번째, "프롬프트 배포 순서"
