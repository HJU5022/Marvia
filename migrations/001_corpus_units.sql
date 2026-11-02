-- 코퍼스 조문 단위 표 (설계 8절 corpus_units, 5.3절 색인). 여러 번 돌려도 결과가 같다(IF NOT EXISTS).
-- [주의] vector(1024)는 설정 embed_dim과 같아야 한다. 바꾸면 표를 지우고 다시 만든 뒤 다시 색인한다.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS corpus_units (
    unit_id text PRIMARY KEY, -- L001556@20261002#제2조.4호.가목
    doc_id text NOT NULL,
    law_name text NOT NULL,
    kind text NOT NULL, -- 법률·시행령·시행규칙·고시
    effective date NOT NULL, -- 시행일
    source_url text NOT NULL,
    heading text NOT NULL, -- 관세법 > 제1장 총칙 > 제2조(정의)
    body text NOT NULL, -- 조문 글 (Unit.text)
    context text NOT NULL DEFAULT '', -- 맥락 문장. 비어 있으면 맥락 문장 없이 색인한 것
    keywords tsvector NOT NULL, -- kiwipiepy로 나눈 낱말
    embedding vector(1024) NOT NULL,
    sha256 text NOT NULL
);

-- [왜] HNSW: 가까운 벡터를 빠르게 찾는 색인. vector_cosine_ops는 코사인 거리(<=>) 검색용
CREATE INDEX IF NOT EXISTS corpus_units_embedding ON corpus_units USING hnsw (embedding vector_cosine_ops);
-- [왜] GIN: tsvector 안의 낱말로 행을 빠르게 찾는 색인
CREATE INDEX IF NOT EXISTS corpus_units_keywords ON corpus_units USING gin (keywords);
