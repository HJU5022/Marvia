# 0014. 새 코드에 기대는 프롬프트는 코드 배포 뒤에 production 라벨을 옮긴다

상태: 채택

## 맥락
서비스는 요청마다 production 라벨의 프롬프트를 읽는다. 코드는 Railway에 손으로 배포한다 ([0009](0009-deploy-railway-not-vercel.md)). 새 도구나 새 입력 칸에 기대는 프롬프트가 코드보다 먼저 바뀌면 없는 도구를 쓰라는 지시가 나간다.

## 결정
1. 프롬프트 글은 레포 파일(`backend/app/prompts/marvia-*.md`)을 먼저 고치고, Langfuse에는 같은 글을 새 버전으로 등록한다. 등록본과 레포 파일이 같은지 확인한다.
2. 새 버전이 새 코드에 기대면, 그 코드가 배포되기 전에는 production 라벨을 옮기지 않는다.
3. 라벨을 옮긴 뒤 트레이스의 prompt_version으로 확인한다. [prompt_versions.md](../prompt_versions.md)에 무엇을, 왜, 결과를, [release_manifest.json](../release_manifest.json)에 현재 production 번호와 되돌릴 번호를 적는다.

## 결과
- 좋아진 것: 등록과 라벨 이동이 나뉘어, 코드 배포 전에는 이전 버전이 계속 쓰인다.
- 대가: 프롬프트와 코드를 따로 배포하는 순서를 사람이 지켜야 한다. 되돌릴 때도 같다. 예로 현재 릴리스 `2026-10-08-r7`은 chat-agent 16을 코드와 함께 배포했고, 되돌릴 번호 15에는 지운 웹 검색 도구 설명이 있어 코드도 함께 되돌려야 한다고 적었다 ([release_manifest.json](../release_manifest.json) `rollback`).

## 근거
- [CLAUDE.md](../../CLAUDE.md) "프롬프트 배포 순서" 절
- [release_manifest.json](../release_manifest.json) `prompts`, `rollback`
- [prompt_versions.md](../prompt_versions.md)
