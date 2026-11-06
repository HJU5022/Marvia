"""실제 LLM·DB·Voyage로 AgentDeps를 만든다 (계획 3a Task 8). 키와 DB가 필요하다.
대화 기록(checkpointer)과 장기 기억(Store)도 Postgres에 둔다 (계획 3d, 설계 8절).
대화 기록은 MARVIA_DATA_KEY에서 뽑은 키로 암호화하고, 암호화하지 않은 값은 읽지 않는다 (R-034, R-038).
암호(AesGcm, EncryptedOnly)를 쓰는 곳이 live_memory뿐이라 여기 둔다.

하지 않는 일: 그래프 흐름(graph/main.py). 테스트는 이 파일 대신 가짜 AgentDeps를 쓴다(conftest.py).
LLM 실패는 llm.structured가 LLMFailed로 바꿔 던지고, 그래프가 잡아 부분 답으로 간다.
"""

from __future__ import annotations

import os
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import psycopg
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from langgraph.checkpoint.base import BaseCheckpointSaver
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


def agent_deps(settings: Settings, conn: psycopg.Connection, watch_conn: psycopg.Connection) -> AgentDeps:
    """설정의 모델과 로컬 DB로 AgentDeps를 만든다. 만들기만 하고 부르지는 않는다.

    conn: RAG 검색·조문 조회가 함께 쓰는 연결. watch_conn: 감시 목록만 쓰는 autocommit 연결.
    """
    llm = chat_model(settings)
    # [왜] 키가 없으면 실제 번호를 저장하지 않는다(fail-closed).
    #      watch=None이면 그래프에 watch_cargo와 새 소식이 없다
    # 틀린 모양의 키(ValueError)도 같다. 오류 글을 그대로 올리지 않는다
    # [왜] 감시는 따로 연결을 쓴다. 같은 단계 도구는 동시에 돌고, 검색·조문 조회는 DB 오류에 conn을 되돌린다.
    #      그 되돌리기가 감시 줄 INSERT와 commit 사이에 끼면 넣었다고 답한 감시 줄이 사라진다 (R-041)
    try:
        watch = live_watch(watch_conn, watch_keys(settings.data_key.get_secret_value()))
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


class EncryptedOnly(EncryptedSerializer):
    """암호화한 값만 읽는 체크포인트 직렬화기. 쓰기는 라이브러리 그대로 늘 암호화한다."""

    def loads_typed(self, data: tuple[str, bytes]) -> Any:
        # [왜] 라이브러리는 형식 이름에 "+암호 이름"이 없으면 평문으로 푼다(encrypted.py loads_typed).
        #      그러면 암호화 전에 쓴 줄과 DB에 직접 넣은 평문 줄도 읽혀 모델 입력까지 간다 (R-038)
        # [주의] 오류 글에 값을 넣지 않는다. 평문 줄에는 실제 번호가 있을 수 있다
        if "+" not in data[0]:
            raise ValueError("암호화되지 않은 체크포인트 값은 읽지 않습니다")
        return super().loads_typed(data)


def checkpoint_serde(secret: str) -> EncryptedSerializer:
    """대화 기록(checkpointer) 직렬화기. MARVIA_DATA_KEY에서 뽑은 키로 AES-GCM 암호화한다."""
    return EncryptedOnly(AesGcm(derive_key(secret, CHECKPOINT_INFO)))


class EncryptedSaver(PostgresSaver):
    """EncryptedOnly를 쓰는 대화 기록 저장기. 엄격 직렬화 모드에서 복제돼도 평문 거절이 남는다."""

    def with_allowlist(self, extra_allowlist: Collection[tuple[str, ...]]) -> BaseCheckpointSaver[str]:
        # [왜] LANGGRAPH_STRICT_MSGPACK=true면 graph.compile이 이 함수로 저장기를 복제하고, 라이브러리가
        #      직렬화기를 기본 EncryptedSerializer로 다시 만든다(checkpoint/base _with_msgpack_allowlist).
        #      그대로 두면 평문 거절이 조용히 사라진다. 복제본의 직렬화기를 다시 EncryptedOnly로 싼다
        clone = super().with_allowlist(extra_allowlist)
        serde = clone.serde
        if isinstance(serde, EncryptedOnly):
            return clone
        if not isinstance(serde, EncryptedSerializer):
            # [주의] 라이브러리가 바뀌어 암호 직렬화기가 아니게 되면 평문을 읽는 쪽으로 가지 않고 멈춘다
            raise TypeError("대화 기록 직렬화기가 암호화 직렬화기가 아닙니다")
        clone.serde = EncryptedOnly(serde.cipher, serde.serde)
        return clone


@contextmanager
def live_memory(url: str, secret: str) -> Iterator[tuple[PostgresSaver, PostgresStore]]:
    """대화 기록(checkpointer)은 암호화해서, 장기 기억(Store)은 그대로 Postgres에 둔다. 표가 없으면 만든다."""
    # [왜] 키가 없거나 틀리면 연결하기 전에 멈춘다(fail-closed). 메모리 대화 기록으로 바꿔 쓰지 않는다.
    #      감시 표와 같은 키 검사다. 오류 글에 비밀이 없다
    watch_keys(secret)
    # [왜] 직렬화기를 거치는 칸(가림 표, 화물, 메시지, Send 묶음, 재개 값, 도구 안 서브그래프 상태)이
    #      모두 암호문이 된다. 장기 기억(품목 카드, 설명 깊이)은 검사에서 번호를 받지 않아 암호화하지 않는다
    # [주의] PostgresSaver.put은 str·int 같은 단순 값 칸을 직렬화기 없이 checkpoints 표 JSONB에 그대로 둔다.
    #        실제 번호가 든 str 칸(text 원문, answer 답)은 저장하지 않는 칸(UntrackedValue)이라
    #        표에 오지 않는다
    #        (graph/state.py, R-035)
    serde = checkpoint_serde(secret)
    with (
        # [왜] from_conn_string은 serde를 받지 않는다. 그 함수와 같은 설정으로 연결을 열고
        #      저장기를 직접 만든다. with 블록을 나가면 연결이 닫힌다
        # [주의] Connection[DictRow]로 적어야 타입 검사기가 줄 모양(dict)을 안다. 저장기는 dict 줄을 받는다
        psycopg.Connection[DictRow].connect(
            url, autocommit=True, prepare_threshold=0, row_factory=dict_row
        ) as conn,
        PostgresStore.from_conn_string(url) as store,
    ):
        saver = EncryptedSaver(conn, serde=serde)
        # [왜] setup은 표가 없을 때만 만들고 있으면 그대로 둔다. 처음 쓰기 전에 꼭 불러야 한다
        saver.setup()
        store.setup()
        yield saver, store
