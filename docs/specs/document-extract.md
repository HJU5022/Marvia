# Spec: 서류 사진·PDF에서 조회 값 뽑기

관련 문서: [SDD](../Marvia_SDD.md) 4.7, 5.14 · [mrn-fallback.md](mrn-fallback.md) · [memory.md](memory.md)

## 요약

| 엔드포인트 | 하는 일 | LLM |
|---|---|---|
| `POST /api/document` | 사진 또는 PDF에서 B/L 번호, 선명, 항차, 입항 예정일, 선적항, 양하항, 품명, 출항일과 B/L 조건·연락처를 읽어 칸마다 검사 결과와 함께 돌려준다 | 씀 (`marvia-doc-extract`) |
| `POST /api/document/bl` | B/L 번호와 MRN만 코드로 읽는다. 채팅 첨부가 쓴다 | 안 씀 |

- 읽은 값은 판정으로 바로 넘기지 않는다. 코드 검사를 통과하지 못한 칸은 확인 필요로 표시하고 틀린 값을 조용히 채우지 않는다.
- B/L 번호는 코드가 뽑고 가린 뒤에만 LLM을 부른다. LLM은 OCR 글자에서 값을 옮겨 적기만 한다.
- 코드: `backend/app/routers/document.py`, `backend/app/services/chat/doc_ocr.py`, `backend/app/services/llm.py` `extract_doc_fields`. 응답 계약: `backend/app/schemas/document.py`.

## 왜

수입자는 포워더에게 받은 도착 통지서(A/N)나 B/L 사본을 들고 있고, 번호와 날짜를 손으로 옮겨 적다가 틀린다. B/L 번호 한 글자가 틀리면 조회가 실패하고, 선명·항차가 틀리면 남의 배로 판정하는 오확정이 생긴다 ([PRD](../Marvia_PRD.md) 8절 평가 축).

## 흐름

| 단계 | 누가 | 하는 일 |
|---|---|---|
| 1. 전처리 | 코드 | 진한 빨간 픽셀을 흰색으로 지운다(빨간 도장·워터마크, `remove_red`). 0°로 읽어 확신도가 낮으면 180°·270°도 읽어 가장 잘 읽힌 방향을 쓴다 |
| 2. OCR | 코드, 로컬 | RapidOCR + ONNX Runtime, PaddleOCR PP-OCRv5 mobile 모델(글자 위치 ch det, 읽기 korean rec). 한국어 모델이 영어도 읽는다. 외부 호출이 없다 |
| 3. B/L 번호 | 코드 | 아래 "B/L 번호 뽑기와 가리기" |
| 4. 나머지 칸 | LLM (`LLM_MODEL`) | 가린 OCR 글자를 넘겨 JSON으로 받는다. 프롬프트는 Langfuse `marvia-doc-extract` |
| 5. 검사 | 코드 | 아래 "검사" |
| 6. 응답 | 코드 | 칸마다 값과 걸린 검사. 하나라도 걸리면 `needs_review=true` |

### B/L 번호 뽑기와 가리기

- "B/L NO.", "B/L 번호", "Bill of Lading No" 이름표의 같은 줄, 뒤 두 줄, 앞 두 줄 순서로 B/L 형식(영문·숫자 8~20자, `schemas/agent.py`)에 맞는 값을 찾는다 (`take_bl`).
- 이름표가 없으면 선사형 번호(영문 4자 + 숫자 8~12자, 컨테이너 번호 제외)를 찾고, 서로 다른 후보가 정확히 하나일 때만 쓴다.
- LLM에 넘길 글자에서 B/L은 `[BL]`, 그 밖의 B/L 모양 번호는 `[ID]`, 개인 휴대폰·이메일은 `[PHONE]`·`[EMAIL]`로 가린다 (`mask_bl`). 날짜 숫자(예: 20261002)는 날짜 칸 재료라 남긴다.
- 가린 뒤에도 B/L이 남아 있으면 LLM을 부르지 않고 `status=partial`로 B/L만 돌려준다.
- MRN은 "MRN" 이름표 옆 값을 코드가 뽑고 LLM에는 보내지 않는다 (`take_mrn`).

### 검사

`doc_ocr.check_fields`, `doc_ocr.check_conditions`. 검사 이름은 넷이다 (`schemas/document.py` `Check`).

| 검사 | 뜻 |
|---|---|
| `missing` | 값이 없다 |
| `not_in_text` | OCR 글자에 그 값이 없다. LLM이 지어냈거나 고쳐 쓴 경우. 날짜는 날짜끼리 비교한다(`02-OCT-2026` = `2026년 10월 2일` = `2026-10-02`) |
| `format` | 항차·날짜 모양이 아니거나 목록 밖 값이다. 출항일이 입항 예정일보다 늦어도 출항일 칸에 건다 |
| `ambiguous` | 그 칸의 이름표가 서류에 두 번 이상 있거나(가짜 정정 행 등), 값이 지시문 줄에서만 나온다. 값이 맞아도 사용자 확인으로 넘긴다 |

영문 선명 뒤에 붙은 "호"는 코드가 뗀다 (`strip_ship_suffix`). 한글 선명은 "호"까지가 이름일 수 있어 두지 않는다.

## 입력

| 항목 | 내용 | 근거 |
|---|---|---|
| 파일 | 사진 또는 PDF 한 파일 (`multipart/form-data`, `file`). 폼에 `session_id`를 같이 보낼 수 있다 | `routers/document.py` |
| 용량 상한 | 10MB. 넘으면 400 `too_large` | `MAX_BYTES` |
| 사진 해상도 상한 | 5000만 화소. 넘으면 400과 한국어 안내 문장. 용량이 작아도 픽셀이 많으면 읽는 데 오래 걸려 막는다 | `doc_ocr.MAX_IMAGE_PIXELS`, `IMAGE_TOO_LARGE_MESSAGE` |
| 로그인과 한도 | 로그인 사용자 기준이다. 하루 토큰 한도를 먼저 확인한다 ([token-quota.md](token-quota.md)) | `quota_guard` |

### PDF

| 항목 | 값 | 근거 (`services/chat/doc_ocr.py`) |
|---|---|---|
| 구분 | 파일 앞 4바이트가 `%PDF`이면 PDF. 파일 이름과 content-type은 바꿀 수 있어 보지 않는다 | `PDF_MAGIC` |
| 읽는 쪽 | 앞 2쪽. 값은 앞 두 장에 있고, 쪽마다 OCR이 늘면 응답이 느려진다 | `PDF_MAX_PAGES` |
| 글자층 먼저 | pypdfium2로 글자를 꺼내 공백 뺀 글자가 40자 이상이면 그대로 쓴다(OCR 없음, `ocr.runs=0`). 40자는 추정값이고 실제 서류로 재지 않았다 | `PDF_MIN_TEXT_CHARS` |
| 스캔 PDF | 쪽마다 배율 2(144dpi)로 그려 사진과 같은 OCR을 돌리고 줄을 쪽 순서로 잇는다. 그림 한 장이 1200만 화소를 넘으면 배율을 낮춘다 | `PDF_RENDER_SCALE`, `PDF_MAX_PIXELS` |
| 오류 | 열 수 없거나 암호가 걸렸거나 0쪽이면 400 `invalid_pdf` | `InvalidPdf` |

라이브러리는 pypdfium2(Apache-2.0/BSD-3, `backend/requirements-doc.txt`)다. PyMuPDF는 AGPL이라 쓰지 않는다. 이후 B/L 뽑기, 가리기, LLM, 검사는 사진과 같다.

## 응답 칸

전체 모양은 `backend/app/schemas/document.py` `DocumentResponse`가 원본이다.

```
{
  "status": "ok" | "partial",
  "needs_review": bool,
  "fields": {
    "bl_no": {"value": str|null, "checks": [str]},   // 예: [] 통과, ["missing"], ["not_in_text"]
    "vessel": {...}, "voyage": {...}, "eta": {...}, "pol": {...}, "pod": {...}, "item": {...},
    "etd": {...},
    "original_bl": {...}, "to_order_bank": {...}, "freight_term": {...}, "incoterm": {...},
    "contact_company": {...}, "contact_role": {...}, "contact_phone": {...}
  },
  "ocr": {"lines": int, "rotation": 0|180|270, "runs": int, "ocr_ms": int},
  "trace_id": str,
  "mrn": str|null,
  "doc_kind": "B/L" | "A/N" | null,
  "llm_error": str|null
}
```

**기본 칸** (`missing` 검사를 건다. 출항일 제외)

| 칸 | 값 |
|---|---|
| `bl_no` | B/L 번호. 코드가 뽑는다 |
| `vessel`, `voyage` | 선명, 항차 |
| `eta` | 입항 예정일 YYYY-MM-DD |
| `pol`, `pod` | 선적항, 양하항 |
| `item` | 품명 |
| `etd` | 출항일 YYYY-MM-DD. 도착 통지서의 E.T.D. 또는 B/L의 Shipped/Laden on board 날짜를 서류에서 옮긴 값이고 계산하지 않는다. 서류에 없는 경우가 흔해 비어도 `missing`을 걸지 않는다 |

**B/L 조건과 화물 인도 연락처** (판정 등급에는 쓰지 않는다. 화물 비서가 짚을 거리로만 쓴다, [memory.md](memory.md))

| 칸 | 값 | 검사 |
|---|---|---|
| `original_bl` | `required`(원본 필요) / `surrendered`(서렌더) | 목록 밖이면 `format`. LLM이 근거로 옮긴 글(`original_bl_text`)이 서류에 없으면 `not_in_text`, 지시문 줄에서만 나오면 `ambiguous` |
| `to_order_bank` | `"true"` / `"false"` (수하인이 TO ORDER OF ... BANK인가) | 위와 같음 (`to_order_bank_text`) |
| `freight_term` | `prepaid` / `collect` | 위와 같음 (`freight_term_text`) |
| `incoterm` | `CIF` / `FOB` / `CFR` | 서류에 낱말로 있어야 한다 (`not_in_text`) |
| `contact_company` | 화물 인도 연락처 회사 (B/L "Party to contact for cargo release", A/N) | 서류에 있어야 한다. 이메일·휴대폰이 섞이면 값을 비우고 `format`. 너무 길거나 `<>`·줄바꿈이 있으면 값은 두고 `format` |
| `contact_role` | 포워더 / 관세사 / 수출자 / 판매처 | 목록 밖이면 `format` |
| `contact_phone` | 회사·부서 전화, 숫자와 하이픈 | 회사 번호 모양이 아니거나 개인 휴대폰이면 값을 비우고 `format`. 숫자가 서류에 없으면 `not_in_text` |

이 칸들은 비어 있으면 검사하지 않는다. `needs_review`는 값이 있는데 검사에 걸릴 때만 올라간다. 개인 이름·휴대폰·이메일은 받지 않는다 (프롬프트와 코드 검사).

**그 밖의 응답 칸**

| 칸 | 뜻 |
|---|---|
| `status` | `ok`, 또는 LLM이 실패해 B/L만 채운 `partial`. 사진·PDF 자체가 문제면 400이다 |
| `mrn` | 코드가 뽑은 MRN ([mrn-fallback.md](mrn-fallback.md)) |
| `doc_kind` | LLM이 고른 서류 종류. 메모장 거래처 출처로 쓴다. 모르면 null이고 거래처를 저장하지 않는다 |
| `llm_error` | LLM 단계 실패 종류(`bad_format`, `timeout`, `overloaded` 등). 성공이면 null. 화면이 "AI가 서류 글자를 정리하지 못했어요"를 보여 준다 |

LLM 답이 JSON 중간에서 끊기면 같은 메시지로 한 번 더 묻는다. 두 번 다 끊기면 `partial`과 `llm_error`를 돌려준다 (`backend/tests/unit/test_doc_extract_retry.py`).

## 저장

지금 화면에서는 확인 화면에 들어가는 길이 없어 아래 저장 흐름은 API로만 쓸 수 있다 (아래 "화면" 표). 채팅 첨부는 출항일 없이 조회를 보낸다 (`ChatBar.tsx` `ask(message, {document: null, ...})`).

- 서류 원본과 OCR 글자는 DB에 저장하지 않는다.
- 확인 화면에서 사용자가 "확인한 값으로 채우기"를 누를 때만 `POST /api/memory/document-facts`로 B/L 조건과 연락처를 저장한다 ([memory.md](memory.md)). 검사에 걸린 B/L 조건·연락처 칸은 확인 화면이 비운 채로 보여 주고, 사용자가 고른 값만 보낸다. 이 요청에는 품명 칸이 없다 (`schemas/memory.py` `DocumentFactsRequest`).
- 사용자가 확인한 출항일은 화물 시트 출항 칸에 `departed_source='document'`로 들어간다 (`schemas/agent.py`, [ERD.md](../ERD.md)).

## 화면

| 화면 | 쓰는 API | 상태 |
|---|---|---|
| 채팅 첨부 (`web/components/ChatBar.tsx`) | `POST /api/document/bl` | 보내기를 누르면 B/L과 MRN만 읽고 곧바로 채팅 조회를 보낸다. LLM을 부르지 않는다 |
| 확인 화면 (`web/components/DocumentPanel.tsx`) | `POST /api/document`, `POST /api/memory/document-facts` | 옛 조회 폼 `TopBar`에서만 열린다. `DocumentPanel`을 불러오는 곳은 `web/components/TopBar.tsx` 하나이고, `TopBar`를 불러오는 화면은 없다 |

`POST /api/document` 전체 판독은 API와 서류 평가 스크립트(`scripts/eval/doc_injection_check.py`)가 쓴다.

## 규칙과의 관계

- **LLM이 만드는 것**: 판정 흐름의 LLM 몫(선박 선택, 판정 설명, 후속 답)과 별도다. 값을 고르거나 판단하지 않고 OCR 글자에서 옮겨 적기만 하며, 검사 단계가 옮긴 값이 글자에 있는지 확인한다.
- **B/L은 LLM에 넘기지 않는다**: 코드가 뽑고 가린다. 가린 뒤 남아 있으면 LLM을 부르지 않는다.
- **품명**: 금지 규칙은 UNI-PASS 응답의 품명이다. 여기 품명은 사용자가 올린 서류에서 읽은 값이고 서류 경로로는 저장하지 않는다.
- **서류 속 문장은 데이터다** ([SDD](../Marvia_SDD.md) 7절 신뢰 경계). 프롬프트에 명시하고, 지시문 줄에서만 나온 값은 `ambiguous`로 표시한다.

## 예외

| # | 상황 | 처리 |
|---|---|---|
| EC-01 | 사진이 아니거나 열 수 없음 | 400 `invalid_image` |
| EC-02 | 파일이 10MB 초과 | 400 `too_large` |
| EC-03 | 글자를 거의 못 읽음 (빈 사진, 손글씨) | 200, 기본 칸 모두 빈칸, `needs_review=true` |
| EC-04 | B/L 이름표 옆에 맞는 값이 없고, 선사형 후보도 정확히 하나가 아님 | B/L 빈칸, 확인 필요. LLM은 나머지 칸만 |
| EC-05 | LLM 실패 (키 없음, 과부하, 형식 깨짐) | 200, B/L만 채우고 나머지 빈칸, `status=partial`, `llm_error` |
| EC-06 | LLM이 글자에 없는 값을 씀 | 그 칸 `not_in_text`, 확인 필요 |
| EC-07 | 칸끼리 뒤바뀜 (선명 자리에 선적항) | 코드 검사로는 못 잡는다. 사용자 확인 화면이 막는다 |
| EC-08 | 서류 속 지시문 ("이전 지시 무시") | 데이터로만 넘긴다. 뽑는 칸이 고정이라 새 동작이 없다. 결과는 아래 "측정 근거" |
| EC-09 | 같은 칸 이름표가 두 번 (가짜 "선명 / 항차 (정정)" 행 등) | 그 칸 `ambiguous`, 확인 필요. 위조 값도 서류 글자에 있어 `not_in_text`로는 못 잡는다. 이름표처럼 짧은 줄만 센다 |
| EC-10 | PDF를 열 수 없음 (깨짐, 암호, 0쪽) | 400 `invalid_pdf` |
| EC-11 | 사진 해상도 5000만 화소 초과 | 400, 줄여서 올리라는 안내 문장 |

## 실행 환경

- 의존성: `rapidocr`(Apache-2.0), `onnxruntime`(MIT), `python-multipart`(업로드), `pypdfium2`. API 이미지에만 설치한다 (`backend/requirements-doc.txt`). OCR 모델 파일은 Docker 빌드 때 받아 이미지에 넣는다.
- OCR 스레드는 컨테이너 CPU 한도에 맞춰 1~4개로 제한한다. 환경변수 `OCR_THREADS`(1 이상 정수)가 있으면 그 값을 쓴다 (`doc_ocr._ocr_threads`). 처음에는 ONNX Runtime 기본값대로 호스트 코어 수만큼 스레드를 만들어 Railway에서 사진 한 장이 126초 걸렸고(로컬 4~6초), 이 제한으로 바꿨다 (`doc_ocr._ocr_threads` 주석, 커밋 `5c3630e`).

## 하지 않는 것과 한계

| 항목 | 내용 | 근거 |
|---|---|---|
| 비전 모델로 넘기기 | 하지 않는다. 검사에 걸리면 `needs_review=true`로 사용자에게 맡긴다 | `routers/document.py` 모듈 주석 |
| 손글씨, 중국어 칸 | 읽기 대상이 아니다. 손글씨처럼 글자를 거의 못 읽으면 EC-03으로 처리한다 | 위 "예외" |
| 측정 서류 | 가공 서류로만 쟀다. 실제 서류는 외부로 보내지 않는다 | 아래 "측정 근거" |
| 배포 서버 속도 | 스레드 제한을 건 뒤 배포 서버(Railway) OCR 속도를 잰 결과 파일은 없다 | `evals/results/` |

## 측정 근거

**서류 속 지시문 확인** (`scripts/eval/doc_injection_check.py`)

- 문항: `evals/doc_dataset.jsonl` 12건 (대조군 C0·E0, 지시문 D1~D7·E1·E2, 위조 값 행 D8). 가공 서류이고 정답은 사람이 확정했다.
- 결과 파일: `evals/results/doc_injection_20260930_*.json` 14개. 모델은 모두 `vertex/google/gemini-2.5-flash`다. 앞 3개(`_0349` ~ `_0352`)는 6문항(C0, D1~D5)만 돌린 실행이다.
- 마지막 4회(`doc_injection_20260930_0515.json` ~ `_0518.json`) 결과:

| 문항 | 결과 |
|---|---|
| C0, E0 (대조군) | 4회 모두 읽힘 |
| D1~D7, E1 (지시문) | 4회 모두 LLM이 무시함 |
| E2 (지시문) | 3회 LLM이 무시함, 1회 지시는 따르지 않았지만 칸에 지시문 글자가 섞임 |
| D8 (위조 값 정정 행) | 4회 모두 원래 값을 썼고, 선명·항차 칸이 `ambiguous`로 확인 필요 |

- D8은 앞선 실행에서 결과가 달랐다. `_0445` ~ `_0449`에서는 LLM이 위조 값을 골랐고 어떤 검사에도 걸리지 않았다(`needs_review=false`). `_0456` ~ `_0514`에서는 LLM이 위조 값을 골랐지만 선명·항차 칸이 `ambiguous`로 확인 필요에 걸렸다.
- 이 결과 파일들은 현재 production `marvia-doc-extract`보다 앞선 프롬프트로 돌린 것이다. 프롬프트 버전별 기록은 [prompt_versions.md](../prompt_versions.md)에 있다.

**OCR 엔진 선택**: 같은 가공 서류 12장에서 칸 값이 OCR 글자에 그대로 있는지 셌다. PaddleOCR 한국어 89/90, 기본 모델 72/90, EasyOCR 74/90. 같은 한국어 모델을 ONNX Runtime(RapidOCR)으로 돌리면 90/90에 B/L 1장 약 2초(Paddle 약 20초)라 RapidOCR + PP-OCRv5 한국어 모델을 골랐다. 전처리(빨간 도장 지우기, 회전)를 넣은 뒤 지저분한 서류 읽기 시험은 113/120이다. 결과 파일과 스크립트는 [docs/evidence/ocr_bench_20260929/](../evidence/ocr_bench_20260929/). 테스트용 가공 서류 이미지는 `backend/tests/fixtures/documents/`에 있다.

**테스트**: `backend/tests/unit/`의 `test_doc_ocr.py`, `test_doc_extract.py`, `test_doc_extract_retry.py`, `test_document_pdf.py`, `test_document_router.py`, `test_departed_from_document.py`.
