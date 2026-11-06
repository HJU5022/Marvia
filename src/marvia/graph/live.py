"""실제 LLM·DB·Voyage로 AgentDeps를 만든다 (계획 3a Task 8). 키와 DB가 필요하다.
대화 기록(checkpointer)과 장기 기억(Store)도 Postgres에 둔다 (계획 3d, 설계 8절).
대화 기록은 MARVIA_DATA_KEY에서 뽑은 키로 암호화한다 (R-034).
암호(AesGcm)를 쓰는 곳이 live_memory뿐이라 여기 둔다.

하지 않는 일: 그래프 흐름(graph/main.py). 테스트는 이 파일 대신 가짜 AgentDeps를 쓴다(conftest.py).
LLM 실패는 llm.structured가 LLMFailed로 바꿔 던지고, 그래프가 잡아 부분 답으로 간다.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import psycopg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
from langgraph.store.postgres import PostgresStore
from psycopg.rows import DictRow, dict_row

from marvia.config import Settings
from marvia.graph.main import AgentDeps
from marvia.graph.schemas import Draft, Plan
from marvia.llm import chat_model, structured
from marvia.rag.live import live_deps
from marvia.rag.provision import find_provision
from marvia.tools.reimport import ItemFacts
from marvia.tools.rules import load_rules
from marvia.watch import derive_key, live_watch, watch_keys

# [왜] 감시 표의 키(marvia-watch-*)와 다른 용도 이름으로 뽑아, 한 쪽 키가 새도 다른 쪽이 열리지 않게 한다
CHECKPOINT_INFO = b"marvia-checkpoint"
CIPHER_NAME = "aesgcm"  # 직렬화 형식 뒤에 "+aesgcm"으로 붙는다. 이 이름이 없는 줄은 암호화 전의 평문이다
NONCE_BYTES = 12  # AES-GCM이 권하는 nonce 길이


def agent_deps(settings: Settings, conn: psycopg.Connection) -> AgentDeps:
    """설정의 모델과 로컬 DB로 AgentDeps를 만든다. 만들기만 하고 부르지는 않는다."""
    llm = chat_model(settings)
    # [왜] 키가 없으면 실제 번호를 저장하지 않는다(fail-closed).
    #      watch=None이면 그래프에 watch_cargo와 새 소식이 없다
    # 틀린 모양의 키(ValueError)도 같다. 오류 글을 그대로 올리지 않는다
    try:
        watch = live_watch(conn, watch_keys(settings.data_key.get_secret_value()))
    except ValueError:
        watch = None
    return AgentDeps(
        rag=live_deps(settings, conn),  # 계획 2의 RAG 바깥 기능을 그대로 쓴다
        plan=structured(llm, Plan),
        item=structured(llm, ItemFacts),
        write=structured(llm, Draft),
        provision=lambda label, as_of: find_provision(conn, label, as_of),
        model=llm,  # [왜] 에이전트 길은 같은 모델에 도구를 묶어 부른다(create_agent가 bind_tools를 한다)
        # [왜] follow_redirects=False: 넘겨 주는 주소를 따라가면 허용 목록 밖으로 갈 수 있다 (official_lookup)
        web=httpx.Client(timeout=load_rules("agent")["official"]["timeout_s"], follow_redirects=False),
        watch=watch,  # 감시 표는 같은 로컬 DB에 있다(migrations/002_watch.sql)
    )


class AesGcm:
    """체크포인트 직렬화기(EncryptedSerializer)에 끼우는 AES-256-GCM 암호. 암호문 앞 12바이트가 nonce다."""

    def __init__(self, key: bytes) -> None:
        self.aead = AESGCM(key)

    def encrypt(self, plaintext: bytes) -> tuple[str, bytes]:
        # [왜] GCM은 한 키로 같은 nonce를 두 번 쓰면 깨진다. 글마다 무작위 nonce를 새로 뽑아 앞에 붙인다
        nonce = os.urandom(NONCE_BYTES)
        return CIPHER_NAME, nonce + self.aead.encrypt(nonce, plaintext, None)

    def decrypt(self, ciphername: str, ciphertext: bytes) -> bytes:
        if ciphername != CIPHER_NAME:
            raise ValueError("모르는 체크포인트 암호 방식입니다")
        # [주의] 키가 다르거나 암호문이 바뀌었으면 InvalidTag를 낸다. 풀지 못한 기록을 읽은 척하지 않는다
        return self.aead.decrypt(ciphertext[:NONCE_BYTES], ciphertext[NONCE_BYTES:], None)


@contextmanager
def live_memory(url: str, secret: str) -> Iterator[tuple[PostgresSaver, PostgresStore]]:
    """대화 기록(checkpointer)은 암호화해서, 장기 기억(Store)은 그대로 Postgres에 둔다. 표가 없으면 만든다."""
    # [왜] 키가 없거나 틀리면 연결하기 전에 멈춘다(fail-closed). 메모리 대화 기록으로 바꿔 쓰지 않는다.
    #      감시 표와 같은 키 검사다. 오류 글에 비밀이 없다
    watch_keys(secret)
    # [왜] 직렬화기를 거치는 칸(가림 표, 화물, 메시지, Send 묶음, 재개 값, 도구 안 서브그래프 상태)이
    #      모두 암호문이 된다. 장기 기억(품목 카드, 설명 깊이)은 검사에서 번호를 받지 않아 암호화하지 않는다
    # [주의] PostgresSaver.put은 str·int 같은 단순 값 칸을 직렬화기 없이 checkpoints 표 JSONB에 그대로 둔다.
    #        그래서 text(사용자 원문)와 answer(번호를 되돌린 답)는 평문으로 남는다.
    #        서버 쪽에서 막는 일은 done.md 4.1
    serde = EncryptedSerializer(AesGcm(derive_key(secret, CHECKPOINT_INFO)))
    with (
        # [왜] from_conn_string은 serde를 받지 않는다. 그 함수와 같은 설정으로 연결을 열고
        #      저장기를 직접 만든다. with 블록을 나가면 연결이 닫힌다
        # [주의] Connection[DictRow]로 적어야 타입 검사기가 줄 모양(dict)을 안다. 저장기는 dict 줄을 받는다
        psycopg.Connection[DictRow].connect(
            url, autocommit=True, prepare_threshold=0, row_factory=dict_row
        ) as conn,
        PostgresStore.from_conn_string(url) as store,
    ):
        saver = PostgresSaver(conn, serde=serde)
        # [왜] setup은 표가 없을 때만 만들고 있으면 그대로 둔다. 처음 쓰기 전에 꼭 불러야 한다
        saver.setup()
        store.setup()
        yield saver, store
