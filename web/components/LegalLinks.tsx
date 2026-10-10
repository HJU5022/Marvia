'use client';
/** 하단 작은 줄: 개인정보처리방침 · 이용약관 · © 2026 Marvia. 누르면 LegalModal로 본문을 연다.
 * 로그인 전 소개 화면 맨 아래와 앱 하단(Shell의 app-footer)에서 같이 쓴다.
 * 이용약관: 안내 서비스라는 한계와 책임 범위. 답마다 붙이던 면책 문구를 대신한다.
 * 처리방침: 레포에 있는 사실만 적는다. 근거: ProfileForm 동의 문구, backend/app/db/migrations/008_purge_queries.sql(90일),
 * backend/app/routers/history.py(내 기록 삭제), backend/app/routers/account.py(탈퇴), docs/specs/memory.md(저장 항목),
 * 015_memory_conditions_purge.sql(끝난 화물 3년), observability/langfuse.py(답변 기록), docs/release_manifest.json(배포 서비스).
 * 레포에 없는 것(사업자 정보, 책임자 연락처, 시행일)은 일부러 비웠다.
 */
import {useState} from 'react';
import {LegalModal} from './LegalModal';

type Which = 'terms' | 'privacy' | null;

export function LegalLinks({className = ''}: {className?: string}) {
  const [open, setOpen] = useState<Which>(null);
  const close = () => setOpen(null);
  return <>
    <div className={`legal-links ${className}`.trim()}>
      <button type="button" onClick={() => setOpen('privacy')}>개인정보처리방침</button>
      <span aria-hidden="true">·</span>
      <button type="button" onClick={() => setOpen('terms')}>이용약관</button>
      <span className="legal-copy">© 2026 Marvia</span>
    </div>
    {open === 'terms' && <LegalModal title="이용약관" onClose={close}><Terms/></LegalModal>}
    {open === 'privacy' && <LegalModal title="개인정보처리방침" onClose={close}><Privacy/></LegalModal>}
  </>;
}

function Terms() {
  return <>
    <h3>서비스 안내</h3>
    <p>Marvia는 수입 화물의 진행 상황을 알려 주는 정보 안내 서비스예요.</p>
    <h3>결과의 한계</h3>
    <p>조회 결과는 공공 데이터(관세청 UNI-PASS, 해양수산부 등)와 AI의 해석으로 만들어요. 시점에 따라 늦거나 사실과 다를 수 있어요.</p>
    <h3>꼭 확인할 것</h3>
    <p>실제 통관과 배송 처리는 포워더나 관세사에게 직접 확인해 주세요. Marvia의 결과만 믿고 내린 결정은 Marvia가 보장하지 않아요.</p>
    <h3>계정</h3>
    <p>설정에서 내 조회 기록을 지우거나 회원 탈퇴를 할 수 있어요.</p>
  </>;
}

function Privacy() {
  return <>
    <h3>수집하는 항목</h3>
    <ul>
      <li>회원 정보: 이름, 휴대전화 번호, 주소</li>
      <li>로그인 이메일 (구글 로그인)</li>
      <li>조회 기록: 조회한 B/L 번호, 판정 결과, 이어서 나눈 대화, 화물 비서가 기억한 날짜와 할 일</li>
    </ul>
    <h3>이용 목적</h3>
    <ul>
      <li>이름, 휴대전화 번호, 주소: 화물 관련 연락과 본인 확인</li>
      <li>이메일: 로그인과 계정 구분</li>
      <li>조회 기록: 내 이력 보기, 지난 조회를 이어서 안내하기</li>
    </ul>
    <h3>보유 기간</h3>
    <ul>
      <li>회원 정보와 계정: 회원 탈퇴 때까지. 탈퇴하면 바로 지워요.</li>
      <li>조회 기록: 90일이 지나면 자동으로 지워요. 설정에서 언제든 직접 지울 수도 있어요.</li>
      <li>탈퇴하면 조회 기록, 대화, 기억한 화물 정보도 함께 지워요.</li>
      <li>끝난 화물 정보는 반출 후 3년이 지나면 자동으로 지워요.</li>
      <li>AI 답변 기록은 품질 확인을 위해 Langfuse에 남아요. 기록 삭제·탈퇴를 해도 여기에는 남을 수 있어요.</li>
    </ul>
    <h3>해외 서비스 이용</h3>
    <p>서비스 운영을 위해 해외 서비스(Railway 서버, Langfuse 기록, Google·OpenRouter AI)를 이용해요. 이 과정에서 가린 B/L 번호, 질문과 답이 해외 서버를 거쳐요.</p>
    <h3>안전하게 보관하는 방법</h3>
    <p>B/L 번호는 암호로 잠가 저장하고 화면에는 일부를 가려서 보여 줘요. 회원 정보도 암호화해서 저장하고, 운영자에게는 가린 값만 보여요.</p>
    <h3>내가 할 수 있는 것</h3>
    <ul>
      <li>열람: 설정에서 내 정보와 조회 기록을 볼 수 있어요.</li>
      <li>삭제: 설정에서 조회 기록을 지울 수 있어요.</li>
      <li>탈퇴: 설정에서 회원 탈퇴를 하면 모든 정보가 지워져요.</li>
    </ul>
    <h3>동의하지 않을 때</h3>
    <p>수집·이용에 동의하지 않아도 되지만, 동의하지 않으면 서비스를 이용할 수 없어요.</p>
  </>;
}
