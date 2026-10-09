# 서류 사진 OCR 실험

서류 사진 읽기(`services/document`)의 OCR 엔진과 2단 구조(OCR 글자 → LLM이 칸 값)를 고른 실험 원본이다. Mac M2 CPU에서 돌렸고, 시험 서류는 모두 가공 이미지다. 실제 B/L은 쓰지 않았다.

| 무엇 | 결과 | 결과 파일 | 스크립트 |
|---|---|---|---|
| OCR 엔진 비교 (12장, 칸 값이 OCR 글자에 그대로 있나) | PaddleOCR 한국어 89/90, 기본 72/90, EasyOCR 74/90 | `2026-09-29_0937_ocr_compare_report.json` | `2026-09-29_0937_ocr_compare.py` |
| 같은 한국어 모델을 ONNX Runtime(RapidOCR)으로 | 90/90, B/L 1장 약 2초 | `2026-09-29_1022_ocr_rapid_report.json` | `2026-09-29_ocr_rapid.py` |
| 지저분한 서류 읽기 (전처리 뒤) | 한국어 모델 113/120, 기본 모델 85/120 | `2026-09-29_1053_ocr_read_pre_report.json` | `2026-09-29_1053_ocr_read_test_v2.py`, `2026-09-29_1053_ocr_preprocess.py` |
| 2단계 칸 값 뽑기 (가공 통지서 6장 + 새 서식 3장) | 63/63, 검사 9/9 통과 | `2026-09-29_1053_ocr_stage2_samples_v2_report.json`, `2026-09-29_1053_ocr_stage2_layouts_v2_report.json` | `2026-09-29_1053_ocr_stage2_v2.py` |

- 가공 서류는 `2026-09-29_0937_ocr_make_samples.py`, `2026-09-29_ocr_make_messy.py`로 만들었다. 테스트용 이미지는 `backend/tests/fixtures/documents/`에 있다
- 읽기 시험의 웹 서류 몇 장은 공개 예시 문서를 로컬에서만 읽었다. 이미지는 여기에 두지 않았고 결과 파일에는 맞았는지 여부만 있다
- 2단계는 프롬프트가 이 서식을 알고 쓴 실험이라 후하게 나온다. 칸끼리 뒤바뀌는 오류(선명 ↔ 선적항)는 검사가 잡지 못한다
