# 0014. 새 코드에 기대는 프롬프트는 코드 배포 뒤에 production 라벨을 옮긴다

상태: 채택

## 맥락
서비스는 요청마다 production 라벨의 프롬프트를 읽는다. 그런데 코드는 Railway에 수동 배포된다 (ADR 0009). 새 도구나 새 입력 칸에 기대는 프롬프트가 코드보다 먼저 바뀌면 없는 도구를 쓰라는 지시가 나간다.

## 결정
1. 프롬프트 글은 레포 파일(`backend/app/prompts/marvia-*.md`)을 먼저 고치고, Langfuse에는 같은 글을 새 버전으로 등록한다. 등록본과 레포 파일이 같은지 확인한다.
2. 새 버전이 새 코드에 기대면, 그 코드가 배포되기 전에는 production 라벨을 옮기지 않는다.
3. 라벨을 옮긴 뒤 트레이스의 prompt_version으로 확인하고, `prompt_versions.md`에 무엇을, 왜, 결과를, `release_manifest.json`에 현재 production 번호와 되돌릴 번호를 적는다.

## 대안
근거 문서에 다른 순서를 검토한 기록이 없다. 이 순서가 생긴 사건(어느 프롬프트가 먼저 바뀌었는지)은 근거 문서에 적혀 있지 않다.

## 결과
좋아진 것: 등록과 라벨 이동이 분리되어, 코드 배포 전에는 이전 버전이 계속 쓰인다. 예로 r6 릴리스는 chat-agent 15 등록 후 되돌릴 번호를 14로 적어 두었다 (`docs/release_manifest.json` rollback).
대가: 프롬프트와 코드를 따로 배포하는 순서를 사람이 지켜야 한다.

## 근거
- `CLAUDE.md` "프롬프트 배포 순서"
- `docs/release_manifest.json` rollback, prompts
- `docs/prompt_versions.md`
