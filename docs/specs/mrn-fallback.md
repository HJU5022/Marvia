# Spec: 세관에 아직 없는 화물은 MRN으로 배 상태까지 (MRN 대체 조회)

관련: [SDD 4.1](../Marvia_SDD.md) (insufficient일 때 MRN 대체 분기), [ERD.md](../ERD.md) (`vessel_source`)

## 현재 동작

- UNI-PASS에 B/L이 없고(insufficient) 요청에 MRN(적하목록 관리번호)이 있으면, 해수부 입항 신고에서 MRN으로 배를 찾고 AIS 위치·남은 거리·입항 예정을 붙여 `status=partial`로 돌려준다
- 판정(verdict)은 하지 않는다. 통관 정보가 없어서다. 답에 "통관 정보는 아직 세관에 없음"을 밝힌다 (`mrn_fallback.NO_CUSTOMS_YET`)
- 해수부에서도 못 찾으면 원래 응답(insufficient)을 그대로 돌려준다

## 왜

- 도착 통지서를 받은 화물이 UNI-PASS 화물통관진행에서 H B/L, M B/L, 화물관리번호 모두 0건인데, 같은 통지서의 MRN은 해수부 입항 신고에 있는 경우가 있었다. 배는 오는데 적하목록이 아직 세관에 없는 시점이다
- 이 기능이 없으면 UNI-PASS에서 못 찾을 때 "정보 확인 필요"로 멈추고, 사용자는 배가 오고 있는지조차 못 본다

## 동작

1. 입력: `AgentRequest.mrn` 선택 칸(11자, 형식 `^[0-9]{2}[A-Z0-9]{8}[IE]$`, 예 `26TESTAB12I`는 가공값). 자연어 입력은 코드가 문장에서 MRN 모양을 뽑고 그 자리를 `[MRN]`으로 바꿔 LLM에 보내지 않는다. 서류 사진은 "MRN" 이름표 옆 값을 코드가 뽑아 `DocumentResponse.mrn`으로 준다
2. UNI-PASS 결과가 insufficient이고 mrn이 있으면, 해수부 입항 신고를 오늘 -3일 ~ +14일 범위에서 찾는다 (`LOOKBACK_DAYS`, `LOOKAHEAD_DAYS`)
3. 찾으면 호출부호로 ShipFinder 후보, 위치, 남은 거리를 기존 MCP 도구로 가져온다. 도구가 실패해도 해수부 정보만으로 partial을 돌려준다
4. 못 찾으면 원래 응답(insufficient) 그대로

**예외**

| # | 상황 | 처리 |
|---|---|---|
| EC-01 | MRN 모양이 아님 | 422 (입력 검증) / 자연어는 MRN으로 안 뽑힘 |
| EC-02 | 해수부에도 없음 | 원래 insufficient 그대로 |
| EC-03 | ShipFinder 실패·한도 | 해수부 입항 예정·접안 시설만으로 partial, evidence에 남김 |
| EC-04 | UNI-PASS 자체 실패(failed) | 대체하지 않는다. 세관 장애는 그대로 알린다 |

**범위 밖**: MRN만으로 하는 첫 조회(B/L 없이), 화물관리번호 조회, 적하목록 API, 판정

## 구현

| 위치 | 책임 |
|---|---|
| `backend/app/schemas/agent.py` | `AgentRequest.mrn` 선택 칸과 형식 검사 (계약 C2) |
| `backend/app/schemas/document.py`, `routers/document.py` | `DocumentResponse.mrn`. 값은 `services/chat/doc_ocr.take_mrn`이 뽑는다 |
| `backend/app/services/chat/ids.py extract_mrn`, `services/chat/patterns.py _MRN` | 자연어에서 MRN을 뽑고 `[MRN]`으로 바꾼다 |
| `backend/app/routers/chat.py ChatContext.mrn` | 채팅 문맥으로 MRN을 넘긴다 |
| `backend/app/services/judge/mrn_fallback.py assess` | 대체 응답 조립. 위치 신선도는 rules.md `position_stale_hours`를 쓰는 `services/watch/vessel_detail._freshness`로 정한다. trusted_eta는 정하지 않는다(통관·판정 없음) |
| `backend/app/routers/agent.py _assess` | UNI-PASS가 insufficient이고 mrn이 있을 때만 대체를 시도한다 |
| `backend/tests/unit/test_mrn_fallback.py` | 테스트 |

## 정상 흐름에서의 MRN

UNI-PASS에서 B/L을 찾은 정상 흐름에서도 세관 기록의 MRN으로 해수부 입항 신고를 찾아 호출부호를 얻고 배를 확정한다 (`services/judge/identify.call_sign_from_mrn`, `routers/agent.py _identify`). 이때 확정 방법은 `user_cargo.vessel_source = 'mrn'`으로 남는다 ([ERD.md](../ERD.md)).
