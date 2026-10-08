# Spec: 서류 사진에서 조회 값 뽑기 (F9 서류 등록, 1차)

PRD 5절 P1 "서류 사진·PDF에서 B/L·선명·ETA 추출(멀티모달)"을 P0로 당긴다는 결정에 따라, SDD에 없는 이 기능의 범위와 동작을 여기 먼저 적는다 (CLAUDE.md "SDD 5절과 작업 리스트에 없는 기능은 docs/specs/에 Spec을 먼저 쓴다").
SDD 1절은 F9를 "인터페이스만 남기고 구현하지 않는다"고 적고 있다. 이 Spec이 그 줄을 대신하고, 코드 동결 전 SDD를 갈아엎을 때 SDD로 옮긴다.

## Why

- **상황**: 수입자는 포워더에게 받은 도착 통지서나 B/L 사본을 들고 있다. B/L 번호, 선명, 항차, 입항 예정일을 손으로 옮겨 적다가 틀린다.
- **문제**: B/L 번호 한 글자가 틀리면 조회 자체가 실패하고, 선명·항차가 틀리면 남의 배로 판정할 수 있다 (PRD 6.1 오확정).
- **가산 항목**: 멀티모달 +5, 모델 라우팅 +3 (가이드 10장). 이 기능이 둘 다에 걸린다.

## Goal

- 사진 한 장을 올리면 7칸(B/L 번호, 선명, 항차, 입항 예정일, 선적항, 양하항, 품명)을 채워 **사용자 확인 화면**에 돌려준다. 판정으로 바로 넘기지 않는다 (SDD 비전 울타리: 추출값은 코드 형식 검증 → 사용자 확인 → 판정).
- 코드 검사를 통과하지 못한 칸은 "확인 필요"로 표시한다. 틀린 값을 조용히 채우지 않는다.
- **Out of Scope (1차)**: 대형 비전 모델로 넘기기(2차), 손글씨, 중국어 칸 읽기, 서류 원본·OCR 글자의 DB 저장. (프론트 화면은 1차에서 빼려 했으나 지금은 만들어져 있다: `DocumentPanel.tsx`. 사용자가 확인한 값만 `POST /api/memory/document-facts`로 저장한다)

## What

### 흐름 (2단 구조)

1. **전처리 (코드)**: 빨간 픽셀을 흰색으로 지운다(빨간 도장·워터마크). 0°로 읽어 확신도가 낮으면 180°·270°도 읽어 가장 잘 읽힌 방향을 쓴다.
2. **OCR (코드, 로컬)**: RapidOCR + ONNX Runtime, PaddleOCR PP-OCRv5 mobile 모델(글자 위치 `ch_PP-OCRv5_det_mobile`, 읽기 `korean_PP-OCRv5_rec_mobile`). 한국어 모델이 영어도 읽는다.
3. **B/L 번호 (코드)**: "B/L NO.", "B/L 번호", "Bill of Lading No" 이름표의 같은 줄, 뒤 두 줄, 앞 두 줄에서 `schemas/agent.py`의 B/L 형식(`^[A-Z0-9]{8,20}$`)에 맞는 값. 찾으면 OCR 글자에서 `[BL]`로 가린다.
4. **나머지 6칸 (소형 LLM, LLM_MODEL)**: 가린 OCR 글자를 넘겨 JSON으로 받는다. 프롬프트는 Langfuse `marvia-doc-extract`.
5. **검사 (코드)**: 빈칸, OCR 글자에 실제로 있나(지어낸 값 차단), 항차 형식, 날짜는 OCR 글자 속 날짜와 날짜로 비교(`02-OCT-2026` = `2026년 10월 2일` = `2026-10-02`). 영문 선명 뒤 "호"는 뗀다.
6. **응답**: 칸마다 값과 검사 결과. 하나라도 걸리면 `needs_review=true`.

### PDF 입력

- **구분**: 파일 앞 4바이트가 `%PDF`이면 PDF다. 파일 이름·content-type은 바꿀 수 있어 보지 않는다. 아니면 기존 사진 경로(`invalid_image` 포함)다.
- **앞 2쪽만** 읽는다. 값은 앞 두 장에 있고, 쪽마다 OCR이 늘면 응답이 느려진다.
- **글자층 먼저**: pypdfium2로 글자를 꺼내 공백 뺀 글자가 40자 이상이면 그 줄을 OCR 결과로 쓴다(OCR 없음, `ocr.runs=0`). 전자 PDF는 글자가 정확하고 빠르다. 40자 미만이면 쪽 번호·워터마크만 있는 스캔 PDF로 보고 넘어간다 (임계값은 추정이며 실제 서류로 재지 않았다).
- **스캔 PDF**: 쪽마다 배율 2(144dpi)로 그려(그림 한 장 1200만 화소 이하로 배율을 낮춘다) 사진과 같은 OCR을 돌리고, 줄을 쪽 순서로 잇는다.
- 이후 B/L 추출·가리기·LLM·검사는 사진과 같다. 라이브러리는 pypdfium2(Apache-2.0/BSD-3, `requirements-doc.txt`). PyMuPDF는 AGPL이라 뺐다.
- **오류**: 열 수 없거나 암호가 걸렸거나 0쪽이면 400 `invalid_pdf`.

### 코드와 맞춘 것

- 입력은 사진 또는 PDF 한 파일이고 상한은 10MB(`routers/document.py MAX_BYTES`, 넘으면 400 `too_large`)다. 폼에 `session_id`를 같이 보낼 수 있다. 로그인이 필수이고 하루 토큰 한도(docs/specs/token-quota.md)를 확인한다
- 7칸 말고 **출항일 `etd`**(도착 통지서의 E.T.D. 또는 B/L의 Shipped/Laden on board 날짜, 서류에서 옮긴 값, 없으면 null)가 더해졌다. 화물 시트의 `departed_source = 'document'`가 이 값에서 온다 (docs/ERD.md)
- 응답에 `mrn`(코드가 "MRN" 이름표 옆에서 뽑음, docs/specs/mrn-fallback.md)과 `llm_error`(LLM 단계가 실패한 종류, 성공이면 null)가 있다. LLM이 실패하면 `status=partial`이고 화면은 AI가 못 읽었다고 안내한다
- PDF 동작은 `services/chat/doc_ocr.py`의 상수(`PDF_MAX_PAGES` 2, `PDF_MIN_TEXT_CHARS` 40, `PDF_RENDER_SCALE` 2, `PDF_MAX_PIXELS` 12,000,000)와 위 서술이 일치한다
- 화면은 `web/components/DocumentPanel.tsx`가 확인 화면을 그린다

### 규칙과의 관계

- **LLM이 만드는 것**: CLAUDE.md는 셋(선박 선택, 판정, 후속 답)이라고 적는다. 이 기능이 넷째다. 값을 "고르거나 판단"하지 않고 OCR 글자에서 "옮겨 적기"만 하며, 검사 5단계가 옮긴 값이 글자에 있는지 확인한다.
- **B/L은 LLM에 안 넘긴다**: 3단계에서 코드가 뽑고 가린다. 가린 뒤 남아 있으면 LLM을 부르지 않는다.
- **품명**: 금지 규칙은 "UNI-PASS 응답의 품명"이다. 여기 품명은 사용자가 올린 서류에서 읽은 값이고, 저장하지 않는다.
- **서류 속 문장은 데이터다** (SDD 7절 신뢰 경계). 프롬프트에 명시한다.

### Edge Cases

| # | 상황 | 처리 |
|---|---|---|
| EC-01 | 이미지가 아니거나 열 수 없음 | 400, `invalid_image` |
| EC-10 | PDF를 열 수 없음 (깨짐, 암호, 0쪽) | 400, `invalid_pdf` |
| EC-02 | 너무 큰 파일 | 400, `too_large` (상한은 라우터 상수) |
| EC-03 | 글자를 거의 못 읽음 (빈 사진, 손글씨) | 200, 7칸 모두 빈칸, `needs_review=true` |
| EC-04 | B/L 이름표가 없거나 형식이 안 맞음 | B/L 빈칸, 확인 필요. LLM은 나머지 칸만 |
| EC-05 | LLM 실패 (키 없음, 과부하, 형식 깨짐) | 200, B/L만 채우고 나머지 빈칸, `status=partial` |
| EC-06 | LLM이 글자에 없는 값을 씀 | 그 칸 `not_in_text`, 확인 필요 |
| EC-07 | 칸끼리 뒤바뀜 (선명 자리에 선적항) | **1차 검사로는 못 잡는다.** 사용자 확인 화면이 막는다 |
| EC-08 | 서류 속에 지시문 ("이전 지시 무시") | 데이터로만 넘긴다. 뽑는 칸이 7개로 고정이라 새 동작이 없다. 확인 결과(`scripts/eval/doc_injection_check.py`, `evals/doc_dataset.jsonl`): 지시문 7종은 거의 전부 무시, "모든 칸 비우기"는 6번 중 1번 따랐지만 빈칸(missing)으로 확인 필요 |
| EC-09 | 같은 칸 이름표가 두 번 (가짜 "선명 / 항차 (정정)" 행 등) | 그 칸 `ambiguous`, 확인 필요. 값이 서류 글자에 있어 not_in_text로 못 잡는다(D8: LLM이 3번 모두 위조 값 채택). 이름표처럼 짧은 줄만 센다 |

## How

```
POST /api/document   (multipart/form-data, file=이미지)

응답 200:
{
  "status": "ok" | "partial",
  "needs_review": bool,
  "fields": {
    "bl_no":  {"value": str|null, "checks": [str]},   // 예: [] 통과, ["missing"], ["not_in_text"]
    "vessel": {...}, "voyage": {...}, "eta": {...},
    "pol": {...}, "pod": {...}, "item": {...}
  },
  "ocr": {"lines": int, "rotation": 0|180|270, "runs": int, "ocr_ms": int},
  "trace_id": str
}
```

### 추가: B/L 조건과 화물 인도 연락처 (docs/specs/memory.md 결정 6·7)

화물 비서 기억이 짚을 거리로만 쓴다. 판정 등급에는 쓰지 않는다.

| 칸 | 값 | 검사 |
|---|---|---|
| `original_bl` | `required`(원본 필요) / `surrendered`(서렌더) | 목록 밖이면 format. LLM이 근거로 옮긴 글(`original_bl_text`)이 서류에 없으면 not_in_text, 지시문 줄에서만 나오면 ambiguous |
| `to_order_bank` | `"true"` / `"false"` (수하인이 TO ORDER OF ... BANK인가) | 위와 같음 (`to_order_bank_text`) |
| `freight_term` | `prepaid` / `collect` | 위와 같음 (`freight_term_text`) |
| `incoterm` | `CIF` / `FOB` / `CFR` | 서류에 낱말로 있어야 한다 (not_in_text) |
| `contact_company` | 화물 인도 연락처 회사 (B/L "Party to contact for cargo release", A/N) | 서류에 있어야 한다. 40자 넘거나 이메일 모양이면 format |
| `contact_role` | 포워더 / 관세사 / 수출자 / 판매처 | 목록 밖이면 format |
| `contact_phone` | 회사·부서 전화, 숫자와 하이픈 | 모양이 아니거나 개인 휴대폰이면 **값을 비우고** format. 숫자가 서류에 없으면 not_in_text |

- 이 칸들은 서류에 없는 경우가 흔해서 비어 있으면 검사하지 않는다(missing 없음). `needs_review`는 값이 있는데 검사에 걸릴 때만 올라간다.
- 응답에 `doc_kind`(`B/L` / `A/N` / null)를 더했다. 메모장 거래처 출처로 쓴다. 모르면 거래처를 저장하지 않는다.
- 개인 이름·휴대폰·이메일은 받지 않는다 (프롬프트 + 코드 검사).
- 저장은 사용자가 확인 화면에서 "확인한 값으로 채우기"를 눌렀을 때만 `POST /api/memory/document-facts`로 한다. 검사에 걸린 칸은 확인 화면이 비운 채로 보여 주고, 사용자가 고른 값만 보낸다. 확인 안 한 OCR 값은 저장하지 않는다.

- 파일: `services/chat/doc_ocr.py`(1~3, 5단계), `services/llm.py` `extract_doc_fields()`(4단계), `routers/document.py`, `schemas/document.py`(계약, 새 파일)
- 의존성: `rapidocr`(Apache-2.0), `onnxruntime`(MIT), `python-multipart`(업로드). 모델 파일은 Docker 빌드 때 받아 이미지에 넣는다

## 근거 (실행한 것만)

실험 폴더 `Main_2_projects/ocr_bench/`(레포 밖), Mac M2 CPU, 2026-09-29. 원본 결과는 팀 위키 근거 원장.

- OCR 후보, 이미지 12장 90칸: PaddleOCR 기본 72 · PaddleOCR 한국어 89 · EasyOCR 74. 한국어 모델을 ONNX Runtime으로 돌리면 90/90, B/L 한 장 약 2초(Paddle 그대로 약 20초)
- 지저분한 사진 10종 + 웹 실제 영어 도착 통지서 4장 + 1853 손글씨 B/L, 120칸: 전처리 후 113/120. 못 읽은 것은 중국어 2칸, 손글씨 3칸, `I225`→`1225`, `가나다무역`→`기나다무역`
- 2단계(가공 통지서 9장, 서식 4종, 63칸): 63/63, 검사 9/9 통과. LLM Gemini 2.5 Flash(Vertex, 생각 0) 1~4초
- 한계: 2단계는 가공 서류로만 쟀다(실제 서류는 외부 전송하지 않기로 함). 배포 서버(Railway) 속도는 미측정

## 채팅 첨부 B/L 읽기와 OCR 스레드

- 채팅 첨부는 칩만 두고 보내기에서 `POST /api/document/bl`로 B/L(과 MRN)만 코드로 읽는다. OCR만 돌려 보통 1~3초이고 LLM을 부르지 않는다. 전체 7칸 판독은 `POST /api/document`가 그대로 맡는다 (실사용 73번, 커밋 `15560af`)
- OCR 스레드를 컨테이너 CPU 쿼터에 맞춰 1~4개로 제한한다. 환경변수 `OCR_THREADS`(1 이상 정수)가 있으면 그 값이다. Railway에서 같은 사진 한 장이 126초 걸리던 문제의 원인이 호스트 코어 수만큼 만든 스레드였다 (실사용 74번, 커밋 `5c3630e`, `services/chat/doc_ocr.py`)
