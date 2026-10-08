"""판정 표 (결정 D7: 확실하면 표, 모르면 LLM이 올리기만).

등급(fine/watch/act)의 1차 결정은 코드가 한다. 표의 재료(어떤 신호면 act인지, 회색 지대 신호, 세지 않는 신호)는
skills/cargo-verdict/rules.md "2층 등급 판정 표" 키에서 읽는다 (재료는 rules.md, 계산 순서는 이 파일).
LLM이 판정 표를 약 14% 안 따랐기 때문이다 (실측: 규칙 1.0, 소형 LLM 0.86. B06·B08·B09).

회색 지대만 LLM이 판단한다:
  act를 가르는 신호(anchor_wait, customs_hold)가 unknown이면 표는 그 신호를 없는 셈 치고 등급을 낮게 낸다.
  예: 부산 앞 속도 0인데 이력이 없어 정지 시간을 모르면 anchor_wait unknown → 표는 fine.
  이때는 LLM이 상황을 읽고 등급을 고른다. 단 표 등급보다 낮출 수는 없다 (raise_only).
그 밖에는 등급이 표로 고정이고, LLM은 그 등급에 맞춰 설명을 쓴다. 표가 틀렸다고 보면 table_disagree에 적고
그 의견은 기록만 된다 (Langfuse generation output, 로그). 사람이 보고 표를 고칠 후보로 쓴다.

평가 베이스라인 (a) 규칙만(evals/baseline_rules.py)도 이 표를 쓴다. 서비스와 평가가 같은 표를 본다.
"""
from backend.app.schemas.agent import Reason
from backend.app.services.judge.rules import rule
from backend.app.services.judge.signals import DEST_BROKEN, DEST_EMPTY

# cargo-verdict/rules.md 판정 표 키. 부를 때마다 rule()로 읽는다 (load_rules가 캐시해서 파일은 한 번만 읽는다)
#   act_signals: 하나라도 triggered면 act
#   gray_signals: 회색 지대를 여는 신호. sales_date_exceeded는 넣지 않는다: unknown이면 판매일을 안 넣은 것(사용자 선택)이거나
#                 도착일 근거가 없는 것인데, 뒤쪽은 라우터가 LLM 전에 보류한다 (_no_eta, D6)
#   ignore_signals · ignore_dest_values: 켜져도 세지 않는 신호 (AIS 입력 오류일 수 있음)
LEVEL = {"fine": 0, "watch": 1, "act": 2}  # 위험 순서. LLM은 표 등급 이상만 낼 수 있다
# 화면·코드 고정 문구에 쓰는 등급 이름 (CLAUDE.md 정의). 라우터 고정 문구와 화물 비서의 "지난 조회" 줄이 같이 쓴다
# 코드(fine/watch/act)는 그대로 두고 한국어 이름만 순항·주의·긴급으로 바꿨다. 이 한 곳이 원본이다
VERDICT_LABEL = {"fine": "순항", "watch": "주의", "act": "긴급"}
# cargo-verdict/rules.md ignore_dest_values의 이름을 signals.py가 dest_changed 값에 쓰는 문장으로 바꾼다
DEST_VALUE = {"broken": DEST_BROKEN, "empty": DEST_EMPTY}


def table_verdict(signal_set, margin: int | None) -> str:
    """cargo-verdict/rules.md "2층 등급 판정 표".
    act: act_signals 중 하나라도 켜짐, 또는 다른 신호가 켜졌는데 여유 일수가 margin_act_days(cargo-verdict/rules.md) 미만
    watch: act_signals는 꺼져 있고 다른 신호가 하나라도 켜짐
    fine: 켜진 신호 없음. unknown(판단 불가)은 켜진 것으로 세지 않는다 (그래서 회색 지대가 생긴다)
    예외: 입력 오류로 설명되는 신호(깨진·빈 목적지, 항해상태 불일치)는 켜져도 세지 않는다 (rules.md ignore_signals · ignore_dest_values)
    """
    on = {s.id for s in signal_set.signals if s.state == "triggered" and not input_error(s)}
    if not on:
        # D4: 다 정상이어도 여유가 margin_act_days 미만이면 watch. 판매일이 없으면(여유 None) 배 상태만으로 fine
        return "watch" if margin is not None and margin < rule("margin_act_days") else "fine"
    if on & set(rule("act_signals")):
        return "act"
    # 여유 일수를 모르면(판매일·도착 예정 없음) 이 조건으로는 act를 내지 않는다
    if margin is not None and margin < rule("margin_act_days"):
        return "act"
    return "watch"


def table_reasons(signal_set, margin: int | None) -> list[Reason]:
    """표 등급의 근거. 켜진 신호를 그대로 든다 (V2: watch·act면 이유 1개 이상, 이름은 신호 id).
    D4 watch는 켜진 신호가 없어서, 여유 일수를 본 신호를 triggered=False로 든다."""
    reasons = [Reason(rule=s.id, value=s.value, triggered=True)
               for s in signal_set.signals if s.state == "triggered"]
    if not reasons and table_verdict(signal_set, margin) == "watch":
        reasons = [Reason(rule="sales_date_exceeded", value=f"여유 {margin}일", triggered=False)]
    return reasons


def is_gray(signal_set) -> bool:
    """회색 지대인가: act를 가르는 신호 중 unknown이 있다."""
    gray = set(rule("gray_signals"))
    return any(s.id in gray and s.state == "unknown" for s in signal_set.signals)


def allowed(llm_verdict: str | None, table: str, gray: bool) -> bool:
    """LLM 등급을 받아도 되나. 회색 지대면 표 이상, 아니면 표와 같아야 한다."""
    if llm_verdict not in LEVEL:
        return False
    return LEVEL[llm_verdict] >= LEVEL[table] if gray else llm_verdict == table


def input_error(signal) -> bool:
    """rules.md 판정 표의 세지 않는 신호. 배의 실제 상태가 아니라 AIS 입력 오류일 수 있는 신호.
    navstat_mismatch: 항해상태는 손으로 넣는 값. 실제 상태는 속도·위치 신호(anchor_wait 등)가 따로 본다"""
    if signal.id in rule("ignore_signals"):
        return True
    ignored = {DEST_VALUE[name] for name in rule("ignore_dest_values")}
    return signal.id == "dest_changed" and signal.value in ignored
