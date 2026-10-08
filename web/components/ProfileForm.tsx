'use client';
/** 회원 정보 입력 (docs/specs/user-profile.md). 두 곳에서 쓴다.
 * - mode="required": 로그인 뒤 정보가 없으면 본문 대신 나온다(Shell). 입력하고 저장을 누르면 동의 창이 떠서, 읽고 동의해야 저장된다
 * - mode="edit": 설정 > 회원 정보에서 본인 정보 확인·수정. 동의는 가입 때 한 번만 받는다: 체크 칸을 두지 않고 작은 글 한 줄만 보인다
 * API 계약은 그대로다: PUT /api/profile은 consent=true가 있어야 저장한다 (routers/profile.py). 이미 저장된 정보가 있으면 동의한 사람이라 true를 보낸다
 * 검사는 서버(services/profile.clean)와 같은 규칙으로 먼저 해서 400을 줄인다. 저장은 서버가 암호화한다.
 */
import {useEffect, useRef, useState, type FormEvent} from 'react';
import {createPortal} from 'react-dom';
import {Check, IdCard, LoaderCircle, LockKeyhole} from 'lucide-react';
import {useApp} from './AppProvider';
import {getProfile, saveProfile} from '@/lib/api';
import type {ProfileData} from '@/lib/types';

/** 숫자만 남겨 010-1234-5678 모양으로. 입력 중에도 보기 좋게 */
function formatPhone(v: string) {
  const d = v.replace(/\D/g, '').slice(0, 11);
  if (d.length < 4) return d;
  if (d.length < 8) return `${d.slice(0, 3)}-${d.slice(3)}`;
  return d.length === 11 ? `${d.slice(0, 3)}-${d.slice(3, 7)}-${d.slice(7)}` : `${d.slice(0, 3)}-${d.slice(3, 6)}-${d.slice(6)}`;
}

function check(p: ProfileData): Record<string, string> {
  const e: Record<string, string> = {};
  const name = p.name.trim().replace(/\s+/g, ' ');
  if (name.length < 1 || name.length > 30) e.name = '이름을 1~30자로 입력해 주세요.';
  if (!/^01[016789]\d{7,8}$/.test(p.phone.replace(/\D/g, ''))) e.phone = '휴대전화 번호를 확인해 주세요. 예: 010-1234-5678';
  const address = p.address.trim().replace(/\s+/g, ' ');
  if (address.length < 5 || address.length > 200) e.address = '주소를 5~200자로 입력해 주세요.';
  return e;
}

/** 개인정보 수집·이용 동의 창. 항목은 예전 "자세히 보기"와 같은 내용이다. 동의하면 onAgree, 취소·Esc·바깥 클릭이면 onClose */
function ConsentModal({busy, onAgree, onClose}: {busy: boolean; onAgree: () => void; onClose: () => void}) {
  const agree = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    agree.current?.focus();
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onClose(); };
    document.addEventListener('keydown', k); return () => document.removeEventListener('keydown', k);
  }, [busy, onClose]);
  // 앱 틀의 transform 영향을 받지 않도록 body 바로 아래에 그린다 (LegalModal과 같은 이유)
  return createPortal(<div className="consent-backdrop" onMouseDown={e => { if (e.target === e.currentTarget && !busy) onClose(); }}>
    <div className="consent-modal" role="dialog" aria-modal="true" aria-labelledby="consent-title">
      <h2 id="consent-title">개인정보 수집·이용 동의</h2>
      <ul>
        <li><span>수집 항목</span>이름, 휴대전화 번호, 주소</li>
        <li><span>이용 목적</span>화물 관련 연락과 본인 확인</li>
        <li><span>보유 기간</span>회원 탈퇴 때까지 (탈퇴하면 바로 지워요)</li>
      </ul>
      <p>동의하지 않아도 되지만, 동의하지 않으면 서비스를 이용할 수 없어요.</p>
      <div className="consent-actions">
        <button type="button" className="button secondary" onClick={onClose} disabled={busy}>취소</button>
        <button type="button" className="button primary" ref={agree} onClick={onAgree} disabled={busy}>{busy ? <LoaderCircle size={15} className="spin"/> : null}동의하고 시작하기</button>
      </div>
    </div>
  </div>, document.body);
}

export function ProfileForm({mode}: {mode: 'required' | 'edit'}) {
  const {user, setProfileComplete} = useApp();
  const [form, setForm] = useState<ProfileData>({name: '', phone: '', address: ''});
  const [consent, setConsent] = useState(false);  // 이미 동의한 사람(저장된 정보가 있는 수정 화면)은 true
  const [askConsent, setAskConsent] = useState(false);  // 동의 창이 열려 있나
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(mode === 'edit');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  // 마지막으로 저장된(불러온) 값. 바뀐 것이 없으면 저장 단추를 막아 "저장했어요"가 거짓으로 뜨지 않게 한다
  const [saved, setSaved] = useState<ProfileData>({name: '', phone: '', address: ''});

  // 수정 화면은 저장된 값을 불러온다. 이미 동의했던 사람이라 동의도 채운다
  useEffect(() => {
    if (mode !== 'edit') return;
    getProfile().then(p => { if (p) { setForm(p); setSaved(p); setConsent(true); } })
      .catch(e => setError(e instanceof Error ? e.message : '회원 정보를 불러오지 못했어요.'))
      .finally(() => setLoading(false));
  }, [mode]);

  // 저장 완료 문구는 단추 옆에 잠깐만 보이고 3초 뒤 사라진다 (큰 상자로 아래에 계속 남아 있었다)
  useEffect(() => { if (!message) return; const t = setTimeout(() => setMessage(''), 3000); return () => clearTimeout(t); }, [message]);
  // 수정 화면에서만 "바뀜" 검사를 한다. 입력 화면(required)은 처음이라 항상 저장할 수 있다. 공백은 서버 정리 규칙처럼 무시하고 비교한다
  const norm = (p: ProfileData) => [p.name.trim().replace(/\s+/g, ' '), p.phone.trim(), p.address.trim().replace(/\s+/g, ' ')].join('|');
  const unchanged = mode === 'edit' && norm(form) === norm(saved);

  /** 저장 단추: 칸 검사 → 동의가 아직이면 동의 창 → 저장. 동의 창은 칸이 맞을 때만 뜬다 */
  function submit(e: FormEvent) {
    e.preventDefault();
    const next = check(form);
    setErrors(next); setMessage(''); setError('');
    if (Object.keys(next).length) return;
    if (!consent) { setAskConsent(true); return; }
    void save(true);
  }

  async function save(agreed: boolean) {
    setBusy(true);
    try {
      const result = await saveProfile({...form, consent: agreed});
      setForm(result); setSaved(result); setConsent(true); setMessage('저장했어요.'); setProfileComplete(true);
    } catch (err) { setError(err instanceof Error ? err.message : '저장하지 못했어요.'); }
    finally { setBusy(false); setAskConsent(false); }
  }

  const set = (k: keyof ProfileData) => (v: string) => setForm(f => ({...f, [k]: k === 'phone' ? formatPhone(v) : v}));

  const body = <form className="profile-form" onSubmit={submit} noValidate>
    <div className="form-field"><label htmlFor="pf-name">이름 <span className="req">필수</span></label>
      <input id="pf-name" value={form.name} onChange={e => set('name')(e.target.value)} autoComplete="name" maxLength={30} aria-invalid={!!errors.name} disabled={busy || loading}/>
      {errors.name && <span className="field-error">{errors.name}</span>}</div>
    <div className="form-field"><label htmlFor="pf-phone">휴대전화 <span className="req">필수</span></label>
      <input id="pf-phone" value={form.phone} onChange={e => set('phone')(e.target.value)} inputMode="numeric" autoComplete="tel" placeholder="010-1234-5678" aria-invalid={!!errors.phone} disabled={busy || loading}/>
      {errors.phone && <span className="field-error">{errors.phone}</span>}</div>
    <div className="form-field wide"><label htmlFor="pf-address">주소 <span className="req">필수</span></label>
      <input id="pf-address" value={form.address} onChange={e => set('address')(e.target.value)} autoComplete="street-address" maxLength={200} placeholder="시·도 시·군·구 도로명 번지" aria-invalid={!!errors.address} disabled={busy || loading}/>
      {errors.address && <span className="field-error">{errors.address}</span>}</div>
    <div className="wide profile-actions">
      <button className="button primary" disabled={busy || loading || unchanged} title={unchanged ? '바뀐 내용이 없어요' : undefined}>{busy ? <LoaderCircle size={15} className="spin"/> : <Check size={15}/>}{mode === 'required' ? '저장하고 시작하기' : '회원 정보 저장하기'}</button>
      <span className="muted"><LockKeyhole size={13}/>{mode === 'edit' && consent ? '개인정보 수집·이용 동의함 · ' : ''}암호화해서 저장하고, 운영자에게도 가린 값만 보여요.</span>
      <span role="status" className="profile-saved">{message}</span>
    </div>
    {error && <p role="alert" className="request-error wide">{error}</p>}
    {askConsent && <ConsentModal busy={busy} onAgree={() => void save(true)} onClose={() => setAskConsent(false)}/>}
  </form>;

  if (mode === 'edit') return <div className="profile-edit">{loading ? <div className="empty-inline"><LoaderCircle size={16} className="spin"/>불러오는 중</div> : body}</div>;

  return <div className="login-page"><section className="login-card profile-card" aria-labelledby="profile-title">
    <span className="eyebrow"><IdCard size={13}/> 마지막 단계</span>
    <h1 id="profile-title">시작하기 전에<br/>회원 정보를 알려 주세요</h1>
    {user?.email && <p className="profile-account">{user.email}</p>}
    {body}
  </section></div>;
}
