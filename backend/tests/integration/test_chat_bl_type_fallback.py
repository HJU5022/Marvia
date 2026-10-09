"""B/L 구분을 말하지 않았을 때 하우스 → 마스터 순서 조회 테스트 (services/chat/chat.py _cargo).

LLM·DB·판정 흐름은 부르지 않는다. test_chat_watch.py의 가짜 llm.chat_agent·가짜 지켜보기 저장소를 그대로 쓴다. B/L은 모의값이다.
"""
from backend.app.routers.agent import NO_CARGO, _response
from backend.app.services.chat import chat as svc
from backend.tests.integration.test_chat_watch import Hooks, USER, _llm, agent_path  # noqa: F401 - agent_path는 같은 환경 설정 fixture

CHECK = [("check_cargo", {"bl_ref": "[BL1]"})]


def _lookup(found_types, failed_types=()):
    """가짜 판정 흐름. found_types에 든 구분으로 부르면 찾고, failed_types면 통관 조회 실패, 나머지는 세관에 없음. 부른 요청을 calls에 모은다."""
    calls = []

    def run(req):
        calls.append(req)
        if req.bl_type in found_types:
            return _response(status="ok", verdict="watch", days_margin=2, answer="조회 결과 답입니다.")
        if req.bl_type in failed_types:
            return _response(status="failed", answer="통관 정보를 가져오지 못했습니다. 잠시 뒤 다시 조회해 주세요.")
        return _response(status="insufficient", missing_inputs=["bl_type"], answer=NO_CARGO)
    return run, calls


def test_house_not_found_then_master_found(monkeypatch):
    _llm(monkeypatch, CHECK)
    run, calls = _lookup({"MASTER"})
    r = svc.handle("TESTBL01 괜찮아?", "s1", None, run)
    assert [c.bl_type for c in calls] == ["HOUSE", "MASTER"]  # 한 번 더, 마스터로
    assert r.request.bl_type == "MASTER" and r.agent.status == "ok"  # 찾은 구분이 뒤에서 쓰인다
    assert "하우스" not in r.reply and "말하지 않아" not in r.reply


def test_house_found_is_single_call(monkeypatch):
    _llm(monkeypatch, CHECK)
    run, calls = _lookup({"HOUSE"})
    r = svc.handle("TESTBL01 괜찮아?", "s1", None, run)
    assert [c.bl_type for c in calls] == ["HOUSE"] and r.request.bl_type == "HOUSE"


def test_both_not_found_is_plain_message(monkeypatch):
    _llm(monkeypatch, CHECK)
    run, calls = _lookup(set())
    r = svc.handle("TESTBL01 괜찮아?", "s1", None, run)
    assert [c.bl_type for c in calls] == ["HOUSE", "MASTER"]
    assert svc.NO_RESULT_BOTH in r.reply
    assert "말하지 않아" not in r.reply and "마스터로 다시" not in r.reply and "구분" not in r.reply
    assert r.agent.missing_inputs == [svc.NOT_FOUND_BOTH]  # 화면의 구분 다시 고르기를 끄는 표식. bl_type가 아니라 화물 표에도 저장되지 않는다


def test_explicit_type_does_not_fall_back(monkeypatch):
    for kind in ("MASTER", "HOUSE"):
        _llm(monkeypatch, [("check_cargo", {"bl_ref": "[BL1]", "bl_type": kind})])
        run, calls = _lookup(set())
        r = svc.handle("TESTBL01 괜찮아?", "s1", None, run)
        assert [c.bl_type for c in calls] == [kind]
        assert svc.NO_RESULT_REPLY in r.reply  # 말한 구분 그대로 한 번만 보고 예전 안내


def test_error_on_house_does_not_fall_back(monkeypatch):
    _llm(monkeypatch, CHECK)
    run, calls = _lookup(set(), failed_types={"HOUSE"})
    r = svc.handle("TESTBL01 괜찮아?", "s1", None, run)
    assert [c.bl_type for c in calls] == ["HOUSE"] and r.agent.status == "failed"


def test_multi_bl_each_falls_back(monkeypatch):
    _llm(monkeypatch, CHECK)
    seen = []

    def run(req):
        seen.append((req.bl_no, req.bl_type))
        ok = req.bl_no == "TESTBL01" and req.bl_type == "HOUSE" or req.bl_no == "TESTBL26" and req.bl_type == "MASTER"
        return _response(status="ok", answer="답") if ok else _response(status="insufficient", missing_inputs=["bl_type"], answer=NO_CARGO)
    r = svc.handle("TESTBL01 TESTBL26 비교해줘", "s1", None, run)
    assert sorted(seen) == [("TESTBL01", "HOUSE"), ("TESTBL26", "HOUSE"), ("TESTBL26", "MASTER")]
    assert {c["bl_no"] for c in r.cargos} == {"TESTBL01", "TESTBL26"} and "하우스 B/L" not in r.reply


def test_photo_style_watch_request_master_found_turns_watch_on(monkeypatch):
    """사진과 함께 "감시 현황에 등록해줄래": 하우스는 없고 마스터가 있으면 마스터로 저장돼 같은 문장의 지켜보기가 켜진다."""
    _llm(monkeypatch, CHECK + [("set_watch", {"on": True})])
    run, calls = _lookup({"MASTER"})
    store = Hooks()
    r = svc.handle("이거 내일 들어온다는데 TESTBL01 감시 현황에 등록 좀 해줄래", "s1", None, run, USER, watch=store.hooks())
    assert [c.bl_type for c in calls] == ["HOUSE", "MASTER"]
    assert store.tool_calls == [("TESTBL01", True)] and r.watch_set == {"bl_no": "TESTBL01", "on": True}
    assert svc.WATCH_ON_REPLY in r.reply


def test_watch_on_cargo_not_found_says_not_found_not_saving(monkeypatch):
    _llm(monkeypatch, CHECK + [("set_watch", {"on": True})])
    run, _ = _lookup(set())
    store = Hooks(fail="not_saved")
    r = svc.handle("TESTBL01 감시 등록해줘", "s1", None, run, USER, watch=store.hooks())
    assert svc.WATCH_NOT_FOUND in r.reply and "저장되는 중" not in r.reply and r.watch_set is None


def test_watch_genuine_not_saved_keeps_saving_message(monkeypatch):
    _llm(monkeypatch, CHECK + [("set_watch", {"on": True})])
    run, _ = _lookup({"HOUSE"})
    store = Hooks(fail="not_saved")
    r = svc.handle("TESTBL01 감시 등록해줘", "s1", None, run, USER, watch=store.hooks())
    assert svc.WATCH_FAIL_REPLY["not_saved"] in r.reply
