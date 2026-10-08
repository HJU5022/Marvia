"""라이브 시연용 데모 화물 10건의 시나리오 목록과, 그것을 재생 문항(evals/fixtures/demo_live.jsonl)으로 펼치는 빌더.

    python -m scripts.demo.demo_live        # 아래 SPECS를 펼쳐 evals/fixtures/demo_live.jsonl을 다시 쓴다 (고치고 나면 한 번 돌린다)

왜 만드나:
  발표 서버는 REPLAY_MODE라 UNI-PASS·ShipFinder·해수부 호출을 파일(evals/fixtures/replay/)이 대신한다. 그 파일을 scripts/demo/make_demo.py가 만든다.
  10건의 상황(순항·주의·긴급, 되묻기, 반출 완료)을 시연에서 바로 보여 주려고, 실제 API 응답처럼 보이는 필드를 모두 채운 모의 화물을 만든다.
  모든 값은 가공값이다. B/L은 DEMO로 시작하고, 선박·포워더·선사·컨테이너 소유자 코드도 DEMO를 넣어 한눈에 모의값임이 보이게 한다 (CLAUDE.md).

새 화물을 더하는 법 (10건 뒤에 10건을 더 쓸 때):
  SPECS 맨 아래에 dict 하나를 더하고 이 파일을 실행한다. 나머지(MMSI·IMO·호출부호·MRN·컨테이너 검사숫자·위치 이력·이력 줄)는 빌더가 채운다.
  `expect`(기대 등급)와 `signals`(켜져야 할 신호)를 같이 적으면 backend/tests/integration/test_demo_live.py가 코드 판정 표(services/judge/verdict.py)로 맞는지 확인한다.

명세 한 줄의 뜻 (시간은 전부 "지금" 기준 시간 단위. 음수는 과거):
  n          번호. 1부터. MRN 글자와 컨테이너 일련번호의 씨앗이다
  bl, title  B/L 번호(DEMO로 시작, 영문+숫자 8~20자)와 화면에 보일 시나리오 이름
  expect     기대 등급 fine·watch·act. 반출 완료처럼 판정을 안 하는 것도 fine이다 (routers/agent.py _released)
  signals    켜져야 하는 신호 id 목록. 없으면 []
  origin     적재항 이름 (PORTS 표에 있어야 한다)
  goods      품명 prnm (영어)
  cntr       컨테이너 일련번호 6자리 목록. 소유자 코드 DEM + U와 검사숫자는 빌더가 붙인다 (ISO 6346)
  fwd, carrier  포워더·선사 이름. fwd가 ""이면 빈 칸으로 온다 (포워더가 비어 오는 화물)
  rows       처리 이력 [(단계 이름, 지금부터 몇 시간)]. 비우면 이력 줄이 없다 (상단 csclPrgsStts를 단계로 쓴다, services/judge/customs.py)
  margin     판매 예정일까지 여유 일수. 판매 예정일 = 믿을 도착일(해수부 실적 > 해수부 예정 > AIS ETA)의 한국 날짜 + margin
  ships      배 목록. 첫 배가 화물의 배다. 둘 이상이면 동명 선박이다 (3번째 항목 설명)
  entry_vs_plan  (선택) 세관 입항일을 해수부 예정에서 몇 시간 옮길지. 기본은 같은 시각 (8번은 -24로 하루 어긋나게 해 서류 대조가 확정하지 못하게 한다)
  sale_in_days   (선택) margin 대신 판매 예정일을 "오늘 + N일"로 직접 정할 때 (반출 완료 10번)
  then       (선택) 되묻기 뒤 사용자가 ships의 몇 번째 배를 골랐는지 {"resolved": 0}. 고른 배로 다시 판정한 결과도 기대값에 적는다
  배 항목: name, nat(세관 국적 2글자), mof_name(해수부 선명이 영문이 아닐 때), pos(속도·방향·항해상태·AIS 목적지·수신 경과 시간),
           path(지나온 길 꼭짓점. 마지막 점이 현재 위치), track(총 점 수, 출발지에 머문 점, 도착지에 멈춘 점),
           ais_eta(AIS ETA), plan(해수부 입항 예정), control(해수부 관제 이벤트), mrn(False면 해수부 신고에 MRN을 안 적는다)

  plan 값이 시간 숫자면 "지금부터 몇 시간"이고, (일, "HH:MM") 쌍이면 "오늘(한국)부터 몇 일 뒤 그 시각"이다. 쌍을 쓰면 판매 예정일이 늘 "오늘 + 일 + 여유"라서
  화면(web/lib/api.ts liveExamples)이 판매 예정일을 채울 수 있다. 이때 AIS ETA는 plan에서 몇 시간 차이인지 ais_vs_plan으로 적는다.
  입항이 이미 끝난 화물(4·5·9번)은 믿을 도착이 과거라 "오늘 + 일"로 못 박을 수 없어 숫자 시간을 쓰고, 판매 예정일을 화면이 채우지 않는다
  (그 셋은 판매 예정일이 비어도 같은 등급이 나온다)

시간이 늘 "지금"처럼 보이게 하는 법:
  이 파일이 쓰는 jsonl은 기준 시각 REF_CLOCK에 맞춘 값이다. 서버에서는 make_demo가 모든 시각을 "지금 - REF_CLOCK"만큼 옮긴다.
  날짜 칸(세관 입항일, 판매 예정일)은 옮긴 시각에서 다시 계산한다 (finalize). 그냥 일 수만 옮기면 자정 전후에 여유 일수가 하루씩 어긋나서
  표의 "여유 9일"이 어떤 시각에 만들었는지에 따라 8일이나 10일이 되고, 동명 선박의 서류 대조(입항일 일치)가 뒤집힌다.
"""
from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from backend.app.services.judge.evidence import KST

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "evals" / "fixtures" / "demo_live.jsonl"
REF_CLOCK = datetime(2026, 10, 6, 12, 0, tzinfo=KST)  # jsonl의 기준 시각. 서버에서는 make_demo가 "지금"으로 옮긴다
HEAD = ("# 라이브 시연용 모의 화물 10건 (모의값). 평가 문항이 아니다: evals/dataset.jsonl과 모양만 같고 평가 실행기는 읽지 않는다. "
        "B/L(DEMO...)·선박(DEMO ...)·MMSI(440999201~211)·호출부호(DMO..)·컨테이너(DEMU...)·포워더·선사·좌표·시각·판매 예정일은 전부 가공값. "
        "손으로 고치지 말고 scripts/demo/demo_live.py의 SPECS를 고친 뒤 python -m scripts.demo.demo_live로 다시 쓴다. "
        "만드는 법: python -m scripts.demo.make_demo. 확인: backend/tests/integration/test_demo_live.py")

# 적재항 이름 -> (UN/LOCODE, 적출국). 세관 ldprCd·lodCntyCd 칸과 해수부 직전 기항지 이름에 쓴다
PORTS = {
    "QINGDAO": ("CNTAO", "CN"), "SHANGHAI": ("CNSHA", "CN"), "NINGBO": ("CNNGB", "CN"), "HO CHI MINH": ("VNSGN", "VN"),
    "TIANJIN XINGANG": ("CNTSN", "CN"), "DALIAN": ("CNDLC", "CN"), "KAOHSIUNG": ("TWKHH", "TW"), "HAIPHONG": ("VNHPH", "VN"),
}
# 세관 국적 코드 -> (ShipFinder 국적, 국적 이름). ShipFinder는 실제로 ISO 이름을 준다. 라우터가 pycountry로 코드와 맞춘다 (_same_nationality)
FLAGS = {"PA": ("Panama", "파나마"), "KR": ("Korea, Republic of", "대한민국"), "LR": ("Liberia", "라이베리아"),
         "SG": ("Singapore", "싱가포르"), "MH": ("Marshall Islands", "마셜제도"), "HK": ("Hong Kong", "홍콩")}

BERTH = (35.08, 128.82)  # 부산 신항 모의 접안 위치. 부산 기준점(skills/port-busan/rules.md busan_ref)에서 약 11해리
ANCHORAGE = (35.00, 129.18)  # 부산 외항 모의 묘박지. 기준점에서 약 9해리 (반경 30해리 안)
TERMINAL = "DEMO 신항 1터미널"
SHED = ("DEMO 신항 1터미널 CY", "99010001")  # 장치장 이름·부호 (모의)

# 이력 줄이 어느 단계인지에 따른 상단 진행상태 (prgsStts, prgsStCd). 마지막 줄 기준. 코드는 모의값이고 CAGE12(반출완료)만 실제 응답에서 봤다
PROGRESS = {
    "입항적재화물목록 제출": ("입항전", "CAGE02"), "입항적재화물목록 심사완료": ("입항전", "CAGE03"),
    "하선신고 수리": ("하선", "CAGE05"), "입항보고 수리": ("입항", "CAGE06"), "입항적재화물목록 운항정보 정정": ("입항전", "CAGE04"),
    "반입신고": ("반입", "CAGE07"), "수입신고": ("수입신고", "CAGE08"), "수입(사용소비) 심사진행": ("수입심사", "CAGE09"),
    "수입신고수리": ("수입신고수리", "CAGE10"), "검사지정": ("검사대기", "CAGE11"), "반출신고": ("반출완료", "CAGE12"),
}
DECLARATION_ROWS = ("수입신고", "수입(사용소비) 심사진행", "수입신고수리", "검사지정", "반출신고")  # 수입신고번호가 붙는 줄
ROW_NOTE = {"반입신고": "입항 반입", "반출신고": "수입신고 수리후 반출", "검사지정": "검사 대상 지정 (서류 심사)"}
ROW_NOTICE = {"검사지정": "검사 대상으로 지정되었습니다. 관세사에게 문의하세요."}  # bfhnGdncCn 사전안내

# ── 시나리오 10건 ────────────────────────────────────────────

# 같은 배 항목에서 겹치는 값: 기본 AIS 목적지는 부산이고 신호는 30분 전에 받았다
def _manifest(*hours):  # 입항 전 화물의 이력: 목록 제출(, 심사완료)
    names = ("입항적재화물목록 제출", "입항적재화물목록 심사완료")
    return [(names[i], h) for i, h in enumerate(hours)]


ARRIVED = ("입항적재화물목록 제출", "입항적재화물목록 심사완료", "하선신고 수리", "입항보고 수리", "반입신고")

SPECS = [
    dict(  # 1. 순항: 황해를 건너는 중, 여유 9일 -> 신호 없음 -> fine
        n=1, bl="DEMOQD2610001", title="순항: 칭다오에서 황해 항해 중", expect="fine", signals=[],
        origin="QINGDAO", goods="RED PEPPER POWDER", cntr=["120938"], fwd="DEMO 가온포워딩", carrier="DEMO 한빛해운",
        weight=18400, pkg=(920, "BG"), vyg="DM41E", margin=9, rows=_manifest(-14),
        ships=[dict(name="DEMO PIONEER", nat="PA", pos=dict(sog=12.4, cog=118), track=(8, 4, 0),
                    path=[(36.06, 120.35), (35.0, 122.8), (34.2, 124.6)], plan=(1, "13:00"), ais_vs_plan=-2, plan_kind="최초")],
    ),
    dict(  # 2. 주의: AIS ETA와 해수부 입항 예정이 18시간 어긋남, 여유 6일 -> eta_conflict -> watch
        n=2, bl="DEMOSH2610002", title="주의: AIS ETA와 입항 예정 18시간 차이", expect="watch", signals=["eta_conflict"],
        origin="SHANGHAI", goods="FROZEN SHRIMP", cntr=["204518"], fwd="DEMO 서진로지스", carrier="DEMO 청해라인",
        weight=21000, pkg=(1050, "CT"), vyg="DS17W", margin=6, rows=_manifest(-20, -8),
        ships=[dict(name="DEMO SEOHAE STAR", nat="KR", mof_name="데모서해스타", pos=dict(sog=13.5, cog=62), track=(8, 5, 0),
                    path=[(30.62, 122.07), (31.8, 124.3), (33.0, 126.2)], plan=(2, "10:00"), ais_vs_plan=-18, plan_kind="변경")],
    ),
    dict(  # 3. 긴급: 도착이 판매 예정일보다 2일 늦다 -> sales_date_exceeded -> act
        n=3, bl="DEMONB2610003", title="긴급: 도착 예정이 판매 예정일보다 2일 늦음", expect="act", signals=["sales_date_exceeded"],
        origin="NINGBO", goods="LED PANEL", cntr=["330671", "330682"], fwd="DEMO 바다로지스", carrier="DEMO 한빛해운",
        weight=9600, pkg=(480, "CT"), vyg="DB09S", margin=-2, rows=_manifest(-22, -10),
        ships=[dict(name="DEMO BLUE TERN", nat="LR", pos=dict(sog=6.2, cog=58), track=(8, 3, 0),  # 저속 항해(태풍 우회)로 도착이 늦어졌다
                    path=[(29.95, 122.05), (30.6, 123.4), (31.4, 124.9)], plan=(4, "06:00"), ais_vs_plan=-5, plan_kind="변경")],
    ),
    dict(  # 4. 긴급: 입항해 보세창고에 반입된 뒤 세관 검사 지정 -> customs_hold -> act
        n=4, bl="DEMOHC2610004", title="긴급: 반입 뒤 세관 검사 지정", expect="act", signals=["customs_hold"],
        origin="HO CHI MINH", goods="COTTON T-SHIRTS", cntr=["418203", "418214"], fwd="DEMO 한결물류", carrier="DEMO 태평양해운",
        weight=14200, pkg=(1180, "CT"), vyg="DN25N", margin=4,
        rows=[*zip(ARRIVED, (-48, -40, -20, -19, -14)), ("수입신고", -11), ("검사지정", -4)],
        ships=[dict(name="DEMO NAMHAE GRACE", nat="SG", pos=dict(sog=0.0, cog=0, nav=5), track=(10, 0, 4),
                    path=[(28.5, 125.0), (31.6, 127.4), (33.6, 128.5), BERTH], ais_eta=-19, plan=-20, plan_kind="변경",
                    control=[("입항", -19, TERMINAL), ("접안", -18, TERMINAL)])],
    ),
    dict(  # 5. 긴급: 부산 30해리 안에서 0.2노트로 30시간 정박 -> anchor_wait -> act
        n=5, bl="DEMOTJ2610005", title="긴급: 부산 앞바다에서 30시간 대기", expect="act", signals=["anchor_wait"],
        origin="TIANJIN XINGANG", goods="STEEL PIPE", cntr=["502947", "502958"], fwd="DEMO 동방익스프레스", carrier="DEMO 청해라인",
        weight=26800, pkg=(210, "PK"), vyg="DT33E", margin=4, rows=_manifest(-70, -60) + [("하선신고 수리", -24)],
        ships=[dict(name="DEMO ORIENT DAWN", nat="MH", pos=dict(sog=0.2, cog=212, nav=1), track=(10, 0, 6),  # 현재 점까지 6점이 한곳에 뭉친다
                    path=[(33.6, 124.0), (33.2, 126.5), (34.2, 128.6), ANCHORAGE], ais_eta=-27, plan=-28, plan_kind="변경",
                    control=[("투묘", -30, "DEMO 외항 묘박지 A")])],
    ),
    dict(  # 6. 주의: 마지막 AIS 위치가 10시간 전 -> position_stale -> watch
        n=6, bl="DEMODL2610006", title="주의: 마지막 위치 수신이 10시간 전", expect="watch", signals=["position_stale"],
        origin="DALIAN", goods="FROZEN GARLIC", cntr=["617035"], fwd="DEMO 오션브릿지", carrier="DEMO 한빛해운",
        weight=17500, pkg=(875, "CT"), vyg="DD52E", margin=7, rows=_manifest(-18, -9),
        ships=[dict(name="DEMO PACIFIC WREN", nat="PA", pos=dict(sog=12.1, cog=140, age=10), track=(8, 5, 0),
                    path=[(38.9, 121.6), (37.4, 122.9), (36.2, 123.9)], plan=(2, "02:00"), ais_vs_plan=-4, plan_kind="최초")],
    ),
    dict(  # 7. 주의: AIS 목적지가 일본 모지(JPMOJ). 부산 아님, 깨짐·빈 값도 아님 -> dest_changed -> watch
        n=7, bl="DEMOKH2610007", title="주의: AIS 목적지가 부산이 아닌 모지", expect="watch", signals=["dest_changed"],
        origin="KAOHSIUNG", goods="PLASTIC RESIN", cntr=["701362", "701373"], fwd="DEMO 해솔포워딩", carrier="DEMO 태평양해운",
        weight=24000, pkg=(960, "BG"), vyg="DK07S", margin=8, rows=_manifest(-26),
        ships=[dict(name="DEMO CORAL BAY", nat="HK", pos=dict(sog=11.5, cog=40, dest="MOJI", code="JPMOJ"), track=(10, 2, 0),
                    path=[(22.55, 120.25), (24.2, 119.7), (26.6, 121.6), (29.5, 126.0)], plan=(2, "16:00"), ais_vs_plan=-6, plan_kind="변경")],
    ),
    dict(  # 8. 되묻기: 같은 이름 배 2척. 서류(세관 입항일)가 하루 어긋나 확정하지 못해 되묻고, 사용자가 고르면 판정한다 -> fine
        n=8, bl="DEMOHP2610008", title="되묻기: 같은 이름 배 2척", expect="insufficient", signals=[],
        origin="HAIPHONG", goods="WOODEN FURNITURE", cntr=["809524", "809535"], fwd="DEMO 다온로지스", carrier="DEMO 한빛해운",
        weight=12800, pkg=(640, "CT"), vyg="DH11E", margin=5, rows=_manifest(-16), entry_vs_plan=-24,  # 세관 입항일은 해수부 예정보다 하루 앞
        then=dict(resolved=0),
        ships=[dict(name="DEMO TWIN CREST", nat="PA", pos=dict(sog=12.5, cog=48), track=(9, 0, 0), mrn=False,  # MRN을 안 적어 MRN으로는 못 찾는다
                    path=[(21.0, 112.5), (24.5, 118.8), (27.0, 122.5)], plan=(2, "14:00"), ais_vs_plan=-2, plan_kind="변경"),
               dict(name="DEMO TWIN CREST", nat="PA", pos=dict(sog=11.0, cog=190, dest="SINGAPORE", code="SGSIN"), track=(9, 2, 0),
                    path=[(20.7, 107.3), (17.0, 108.9), (13.0, 109.8)], ais_eta=140, plan=None)],  # 같은 이름의 다른 배. 해수부 부산 신고가 없다
    ),
    dict(  # 9. 순항: 입항해 수입신고 수리까지 끝, 컨테이너 3개, 포워더 빈 칸, 여유 5일 -> fine
        n=9, bl="DEMOSH2610009", title="순항: 입항 후 수입신고 수리", expect="fine", signals=[],
        origin="SHANGHAI", goods="AUTO PARTS", cntr=["925706", "925717", "925728"], fwd="", carrier="DEMO 청해라인",
        weight=19800, pkg=(330, "CT"), vyg="DJ63W", margin=5,
        rows=[*zip(ARRIVED, (-50, -40, -18, -19, -14)), ("수입신고", -12), ("수입(사용소비) 심사진행", -9), ("수입신고수리", -5)],
        ships=[dict(name="DEMO JADE RIVER", nat="LR", pos=dict(sog=0.0, cog=0, nav=5), track=(10, 0, 4),
                    path=[(30.62, 122.07), (31.6, 124.3), (33.2, 126.7), (34.5, 128.5), BERTH], ais_eta=-19, plan=-20, plan_kind="변경",
                    control=[("입항", -19, TERMINAL), ("접안", -18, TERMINAL)])],
    ),
    dict(  # 10. 반출 완료: 반출신고가 마지막 이력 -> 배를 찾지 않고 ok + fine (routers/agent.py _released)
        n=10, bl="DEMOQD2610010", title="반출 완료: 창고에서 나간 화물", expect="fine", signals=[],
        origin="QINGDAO", goods="STAINLESS BOWLS", cntr=["031859"], fwd="DEMO 청솔포워딩", carrier="DEMO 한빛해운",
        weight=7200, pkg=(360, "CT"), vyg="DQ78E", sale_in_days=3,
        rows=[("입항적재화물목록 제출", -144), ("입항적재화물목록 심사완료", -139), ("입항적재화물목록 운항정보 정정", -132),
              ("하선신고 수리", -125), ("입항보고 수리", -121), ("반입신고", -116), ("수입신고", -108),
              ("수입(사용소비) 심사진행", -104), ("수입신고수리", -101), ("반출신고", -92)],
        ships=[dict(name="DEMO SILVER GULL", nat="MH", pos=dict(sog=13.0, cog=65, dest="OSAKA", code="JPOSA"), track=(8, 1, 0),
                    path=[(36.07, 120.4), (35.5, 124.0), (34.2, 128.6), (35.0, 129.3), (33.9, 131.0)], ais_eta=30, plan=None,
                    control=[("입항", -122, TERMINAL), ("접안", -121, TERMINAL), ("출항", -100, TERMINAL)])],
    ),
]


# ── 값 만들기 ────────────────────────────────────────────────

# ISO 6346 글자값: A=10부터 11의 배수(11, 22, 33)를 건너뛴다
_LETTER = {c: v for c, v in zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", [10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 26, 27, 28, 29, 30,
                                                               31, 32, 34, 35, 36, 37, 38])}


def container_no(serial: str) -> str:
    """DEM + U + 일련번호 6자리 + 검사숫자 1자리 (ISO 6346). 소유자 코드 DEM은 모의값이라 실제 컨테이너와 겹치지 않는다.
    검사숫자: 앞 10글자의 값 x 2의 자리수(0~9) 합을 11로 나눈 나머지, 10이면 0."""
    head = "DEMU" + serial
    total = sum((_LETTER[c] if c.isalpha() else int(c)) * 2 ** i for i, c in enumerate(head))
    return head + str(total % 11 % 10)


def imo_number(base: int) -> int:
    """IMO 번호 = 앞 6자리 + 검사숫자 (앞 6자리에 7,6,5,4,3,2를 곱해 더한 값의 끝자리). 모의 앞자리는 999로 시작한다."""
    digits = [int(c) for c in str(base)]
    return int(str(base) + str(sum(d * w for d, w in zip(digits, (7, 6, 5, 4, 3, 2))) % 10))


def _at(hours: float) -> datetime:
    return REF_CLOCK + timedelta(hours=hours)


def hours_of(value) -> float:
    """시간 값을 REF_CLOCK 기준 시간 단위로. 숫자는 그대로, (일, "HH:MM") 쌍은 기준일(한국)에서 일 뒤 그 시각까지의 시간이다."""
    if isinstance(value, (int, float)):
        return value
    day, clock = value
    hour, minute = map(int, clock.split(":"))
    target = datetime.combine(REF_CLOCK.date() + timedelta(days=day), datetime.min.time(), tzinfo=KST) + timedelta(hours=hour, minutes=minute)
    return (target - REF_CLOCK).total_seconds() / 3600


def _iso(hours: float) -> str:
    return _at(hours).isoformat()


def _epoch(hours: float) -> int:
    return int(_at(hours).timestamp())


def _midpoint(path: list[tuple], fraction: float) -> tuple[float, float]:
    """꼭짓점을 이은 길에서 처음부터 fraction(0~1) 만큼 간 점. 길이는 위도·경도 차이로 어림한다(모양을 그리는 데는 충분하다)."""
    legs = [((a[0] - b[0]) ** 2 + ((a[1] - b[1]) * 0.82) ** 2) ** 0.5 for a, b in zip(path, path[1:])]
    want = fraction * sum(legs)
    for (a, b), leg in zip(zip(path, path[1:]), legs):
        if want <= leg or (a, b) == (path[-2], path[-1]):
            t = min(1.0, want / leg) if leg else 1.0
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        want -= leg
    return path[-1]


def make_track(ship: dict, mmsi: int) -> list[dict]:
    """6시간 간격 위치 이력(워커 positions 표와 같은 모양)을 오래된 순으로 만든다. 마지막 점이 현재 위치(수신 시각)다.

    track=(총 점 수, 출발지에 머문 점, 도착지에 멈춘 점):
      - 처음 `dwell`점은 길의 첫 점에 머문다 (출항 전 대기). 속도 0.3노트
      - 마지막 `stop`점은 길의 끝에 멈춘다 (접안·묘박). 속도는 현재 속도. 멈춘 점은 몇 미터 흔들려 실제 AIS처럼 한 점으로 안 겹친다
      - 가운데 점은 길을 따라 고르게 간다. 속도는 현재 속도 근처
    anchor_wait는 이 이력에서 멈춘 점이 이어진 시간을 잰다 (services/judge/signals.py _anchor_wait)."""
    total, dwell, stop = ship["track"]
    path, pos = ship["path"], ship["pos"]
    movers = total - dwell - stop
    rng = random.Random(mmsi)  # 같은 배는 늘 같은 이력
    cruise = pos["sog"] if pos["sog"] > 1 else 12.0
    points = []
    for index in range(total):  # 0이 가장 오래된 점
        if index < dwell:
            lat, lng = path[0]
            sog = 0.3
        elif index >= total - stop:
            lat, lng = path[-1]
            sog = pos["sog"]
        else:
            step = index - dwell + 1
            lat, lng = _midpoint(path, step / (movers + (1 if stop else 0)))
            sog = round(cruise + rng.uniform(-0.6, 0.6), 1)
        if index < dwell or index >= total - stop:
            lat, lng = lat + rng.uniform(-0.0006, 0.0006), lng + rng.uniform(-0.0006, 0.0006)
        points.append((lat, lng, sog))
    points[-1] = (path[-1][0], path[-1][1], pos["sog"])  # 현재 점은 위치 응답과 정확히 같다 (흔들림 없이)
    age = pos.get("age", 0.5)
    return [{"at": _iso(-age - 6 * (total - 1 - index)), "lat": round(lat, 4), "lng": round(lng, 4), "sog": sog}
            for index, (lat, lng, sog) in enumerate(points)]


def _unipass(spec: dict, main: dict, mrn: str, entry_day: date) -> dict:
    """UNI-PASS 응답 한 건의 요약값. evals/replay_fixtures._write_unipass가 실제 API001 모양의 XML로 쓴다."""
    code, country = PORTS[spec["origin"]]
    n = spec["n"]
    rows = sorted(spec.get("rows") or [], key=lambda r: r[1])
    last = rows[-1][0] if rows else "입항적재화물목록 제출"
    status, status_code = PROGRESS[last]
    shed, shed_code = SHED
    history = []
    for name, hours in reversed(rows):  # 응답은 최신이 위
        row = {"cargTrcnRelaBsopTpcd": name, "prcsDttm": _at(hours).strftime("%Y%m%d%H%M%S"), "shedNm": shed, "shedSgn": shed_code,
               "rlbrCn": ROW_NOTE.get(name, ""), "bfhnGdncCn": ROW_NOTICE.get(name, ""),
               "pckGcnt": spec["pkg"][0], "pckUt": spec["pkg"][1], "wght": spec["weight"], "wghtUt": "KG"}
        if name == "입항보고 수리":  # 배 입항 신고라 화물 칸이 없다 (evals/fixtures/unipass/progress_ok.xml)
            row.update(shedNm="", shedSgn="", pckGcnt="", pckUt="", wght="", wghtUt="")
        if name in DECLARATION_ROWS:
            row["dclrNo"] = f"DEMO-26-{n:02d}0001"
        if name == "반출신고":
            row.update(rlbrDttm=row["prcsDttm"], rlbrBssNo=row["dclrNo"])
        history.append(row)
    return {
        "cargMtNo": mrn + "0001" + "0001",  # 화물관리번호 19자 = MRN 11 + MSN 4 + HSN 4 (services/judge/customs.py)
        "shipNm": main["name"], "shipNat": main["nat"], "shipNatNm": FLAGS[main["nat"]][1], "vydf": spec["vyg"],
        "etprDt": entry_day.strftime("%Y%m%d"), "etprCstm": "부산세관",
        "csclPrgsStts": last, "prgsStts": status, "prgsStCd": status_code,
        "ldprCd": code, "ldprNm": spec["origin"], "lodCntyCd": country, "dsprCd": "KRPUS", "dsprNm": "부산항",
        "prnm": spec["goods"], "ttwg": spec["weight"], "wghtUt": "KG", "cargTp": "수입 일반화물",
        "rlseDtyPridPassTpcd": "N", "dclrDelyAdtxYn": "N",
        "mblNo": f"DEMOMBL{n:07d}", "hblNo": spec["bl"],
        "cntrGcnt": len(spec["cntr"]), "cntrNo": [container_no(s) for s in spec["cntr"]],
        "shcoFlcoSgn": "DMHB", "shcoFlco": spec["carrier"], "frwrSgn": "DMFW" if spec["fwd"] else "", "frwrEntsConm": spec["fwd"],
        "history": history,
    }


def expand(spec: dict, first_ship: int) -> tuple[dict, int]:
    """명세 한 줄을 재생 문항(dict) 하나로 펼친다. 돌려주는 값: (문항, 다음 배 번호). 배 번호가 MMSI·IMO·호출부호를 정한다."""
    n = spec["n"]
    mrn = f"26DMO{chr(64 + n)}{n:04d}I"  # 입항 MRN 11자: 연도 2 + DMO + 구분 글자 + 일련번호 4 + I (끝이 I면 입항, services/judge/customs.py)
    ships, searches, positions, flags, tracks, arrivals, controls = [], [], {}, {}, {}, [], []
    for offset, ship in enumerate(spec["ships"]):
        idx = first_ship + offset
        if ship.get("plan") is not None:  # 해수부 예정 시각(시간 단위). AIS ETA는 plan 기준 차이(ais_vs_plan)나 직접 값(ais_eta)
            ship["plan_h"] = hours_of(ship["plan"])
            if "ais_vs_plan" in ship:
                ship["ais_eta"] = ship["plan_h"] + ship["ais_vs_plan"]
        mmsi, call = 440999200 + idx, f"DMO{idx:02d}"
        imo = imo_number(999000 + idx)
        pos = {"dest": "BUSAN", "code": "KRPUS", "nav": 0, "age": 0.5, **ship["pos"]}
        ship["pos"] = pos
        last_time = _epoch(-pos["age"])
        positions[str(mmsi)] = {
            "mmsi": mmsi, "imo": imo, "call_sign": call, "ship_name": ship["name"], "ship_cnname": "", "data_source": 0, "ship_type": 70,
            "length": 190, "width": 32, "left": 20, "trail": 170, "draught": 9.5, "dest": pos["dest"], "destcode": pos["code"],
            **({"eta": _epoch(ship["ais_eta"])} if ship.get("ais_eta") is not None else {}),
            "navistat": pos["nav"], "lat": ship["path"][-1][0], "lng": ship["path"][-1][1], "sog": pos["sog"], "cog": pos["cog"],
            "hdg": pos["cog"], "rot": 0, "last_time": last_time,
        }
        searches.append({"match_type": 1, "mmsi": mmsi, "imo": imo, "call_sign": call, "ship_name": ship["name"], "data_source": 0,
                         "last_time": last_time})
        flags[str(mmsi)] = FLAGS[ship["nat"]][0]
        tracks[str(mmsi)] = make_track(ship, mmsi)
        if ship.get("plan") is not None:  # 해수부 입항 신고. 최종(입항 뒤)이 아닌 최초·변경만 예정으로 쓰인다 (clients/mof.py)
            arrivals.append({"clsgn": call, "vsslNm": ship.get("mof_name") or ship["name"], "vsslNltyCd": ship["nat"],
                             "reqstSeNm": ship.get("plan_kind", "변경"), "etryptDt": _iso(ship["plan_h"]), "laidupFcltyNm": None,
                             "prvsDpmprtPrtNm": spec["origin"], "mrNum": mrn if ship.get("mrn", True) else None})
        controls += [{"clsgn": call, "cntrlNm": kind, "cntrlOpertDt": _iso(hours), "fcltyNm": place}
                     for kind, hours, place in ship.get("control", [])]
        ships.append(ship)
    main = ships[0]

    # 믿을 도착 시각(시간 단위): 해수부 실적 > 해수부 예정 > AIS ETA (services/judge/signals.trusted_eta). 화물의 배(첫 배) 기준
    arrived = [h for kind, h, _ in main.get("control", []) if kind in ("입항", "접안")]
    trusted = min(arrived) if arrived else main["plan_h"] if main.get("plan") is not None else main.get("ais_eta")
    entry = trusted + spec["entry_vs_plan"] if spec.get("entry_vs_plan") is not None else trusted
    record_fixtures = {
        "clock": REF_CLOCK.isoformat(),
        "unipass": _unipass(spec, main, mrn, REF_CLOCK.date()),
        "shipfinder": {"search": searches, "flag": flags, "position": None, "positions": positions},
        "worker_positions": tracks,
        "mof": {"arrival_reports": arrivals, "control_events": controls},
        # finalize()가 날짜 칸을 다시 계산하는 데 쓰는 기준 시각들. make_demo가 시각을 옮길 때 같이 옮겨진다
        "entry_at": _iso(entry if entry is not None else 0),
        "trusted_eta": _iso(trusted) if trusted is not None else None,
    }
    expect = spec["expect"]
    first = {"status": "insufficient", "match": "uncertain"} if expect == "insufficient" else \
        {"status": "ok", "match": "none" if spec["rows"] and spec["rows"][-1][0] == "반출신고" else "confirmed"}
    record = {
        "id": f"L{n:02d}", "category": "demo_live", "failure_kind": None, "demo_title": spec["title"],
        "request": {"bl_no": spec["bl"], "bl_type": "HOUSE", "sale_due_date": None, "session_id": f"demo-L{n:02d}",
                    "follow_up_question": None, "resolved_mmsi": None, "voyage_no": None, "forwarder_eta": None},
        "fixtures": record_fixtures,
        "demo_margin": spec.get("margin"), "demo_sale_in_days": spec.get("sale_in_days"),
        "expected_verdict": None if expect == "insufficient" else expect, "expected_status": first["status"],
        "expected_vessel_match": first["match"], "expected_mmsi": None if first["match"] != "confirmed" else searches[0]["mmsi"],
        "expected_missing_inputs": ["voyage_no", "forwarder_eta"] if expect == "insufficient" else [],
        "expected_signals": spec["signals"],
        "label_reason": f"{spec['title']}. 코드 판정 표(services/judge/verdict.py)로 정한 기대 등급이다. 확정은 제품 책임자가 검토한다.",
        "labeler": None, "labeled_at": None, "actual_arrival": None,
    }
    if isinstance(main.get("plan"), list):  # (일, "HH:MM") 쌍. finalize가 오늘 + 일의 그 시각으로 다시 못 박는다
        record["demo_anchor"] = {"day": main["plan"][0], "time": main["plan"][1], "call_sign": searches[0]["call_sign"]}
        record["demo_sale_in_days"] = main["plan"][0] + spec["margin"]  # 화면이 채울 판매 예정일 = 오늘 + 이 일 수
    if spec.get("then"):  # 되묻기 뒤 사용자가 배를 골랐을 때의 기대 결과
        picked = searches[spec["then"]["resolved"]]["mmsi"]
        record["then"] = {"request": {"resolved_mmsi": picked}, "expected_status": "ok", "expected_verdict": "fine",
                          "expected_vessel_match": "confirmed", "expected_mmsi": picked}
        record["demo_final_verdict"] = "fine"
    finalize(record)
    return record, first_ship + len(spec["ships"])


def finalize(record: dict) -> dict:
    """세관 입항일(etprDt)과 판매 예정일을 fixtures의 기준 시각에서 다시 계산해 record에 쓴다 (모듈 설명 "시간이 늘 지금처럼").

    1) demo_anchor가 있으면(plan이 (일, "HH:MM") 쌍인 화물) 화물의 배의 해수부 입항 예정을 "오늘(한국) + 일"의 그 시각으로 다시 정한다.
       같은 만큼 그 배의 AIS ETA, 믿을 도착(trusted_eta), 세관 입항 기준(entry_at)도 옮겨 서로의 차이는 그대로 둔다.
       그러면 판매 예정일이 어느 시각에 만들어도 오늘 + 일 + 여유라서 화면이 미리 채울 수 있다.
    2) entry_at의 한국 날짜가 세관 입항일이다. 해수부 예정과 같은 시각 값에서 뽑으므로 시각을 옮겨도 날짜가 어긋나지 않는다.
    3) 판매 예정일 = trusted_eta의 한국 날짜 + demo_margin. margin이 없으면 오늘 + demo_sale_in_days.
    make_demo가 시각을 옮긴 뒤에 다시 부른다. 반환값은 같은 record다."""
    fixtures = record["fixtures"]
    today = datetime.fromisoformat(fixtures["clock"]).astimezone(KST).date()
    anchor = record.get("demo_anchor")
    if anchor:
        hour, minute = map(int, anchor["time"].split(":"))
        target = datetime.combine(today + timedelta(days=anchor["day"]), datetime.min.time(), tzinfo=KST) + timedelta(hours=hour, minutes=minute)
        move = target - datetime.fromisoformat(fixtures["trusted_eta"])
        for report in fixtures["mof"]["arrival_reports"]:
            if report["clsgn"] == anchor["call_sign"]:
                report["etryptDt"] = (datetime.fromisoformat(report["etryptDt"]) + move).isoformat()
        for position in fixtures["shipfinder"]["positions"].values():
            if position["call_sign"] == anchor["call_sign"] and "eta" in position:
                position["eta"] += int(move.total_seconds())
        for key in ("trusted_eta", "entry_at"):
            fixtures[key] = (datetime.fromisoformat(fixtures[key]) + move).isoformat()
    entry = datetime.fromisoformat(fixtures["entry_at"]).astimezone(KST).date()
    fixtures["unipass"]["etprDt"] = entry.strftime("%Y%m%d")
    if record.get("demo_margin") is not None and fixtures.get("trusted_eta"):
        sale = datetime.fromisoformat(fixtures["trusted_eta"]).astimezone(KST).date() + timedelta(days=record["demo_margin"])
    else:
        sale = today + timedelta(days=record.get("demo_sale_in_days") or 0)
    record["request"]["sale_due_date"] = sale.isoformat()
    return record


def build_records() -> list[dict]:
    """SPECS 전부를 펼친다. 배 번호는 명세 순서대로 1부터 이어진다 (동명 선박은 두 번호를 쓴다)."""
    records, next_ship = [], 1
    for spec in SPECS:
        record, next_ship = expand(json.loads(json.dumps(spec)), next_ship)  # SPECS를 건드리지 않게 복사해서 쓴다
        records.append(record)
    return records


def render() -> str:
    """jsonl 파일 내용. 첫 줄은 '#' 머리 설명이고 읽는 쪽(make_demo.load_live)이 건너뛴다."""
    return "\n".join([HEAD, *(json.dumps(r, ensure_ascii=False) for r in build_records())]) + "\n"


def main() -> None:
    OUTPUT.write_text(render(), encoding="utf-8")
    print(f"{OUTPUT.relative_to(ROOT)}: {len(SPECS)}건")


if __name__ == "__main__":
    main()
