'use client';
/** 회원 정보 입력 (docs/specs/user-profile.md). 두 곳에서 쓴다.
 * - mode="required": 로그인 뒤 정보가 없으면 본문 대신 나온다(Shell). 입력하고 동의해야 서비스를 쓴다
 * - mode="edit": 설정 > 계정과 기록에서 본인 정보 확인·수정
 * 검사는 서버(services/profile.clean)와 같은 규칙으로 먼저 해서 400을 줄인다. 저장은 서버가 암호화한다.
 */
import {useEffect, useState, type FormEvent} from 'react';
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

function check(p: ProfileData, consent: boolean): Record<string, string> {
  const e: Record<string, string> = {};
  const name = p.name.trim().replace(/\s+/g, ' ');
  if (name.length < 1 || name.length > 30) e.name = '이름을 1~30자로 입력해 주세요.';
  if (!/^01[016789]\d{7,8}$/.test(p.phone.replace(/\D/g, ''))) e.phone = '휴대전화 번호를 확인해 주세요. 예: 010-1234-5678';
  const address = p.address.trim().replace(/\s+/g, ' ');
  if (address.length < 5 || address.length > 200) e.address = '주소를 5~200자로 입력해 주세요.';
  if (!consent) e.consent = '개인정보 수집·이용에 동의해야 이용할 수 있어요.';
  return e;
}

export function ProfileForm({mode}: {mode: 'required' | 'edit'}) {
  const {user, setProfileComplete} = useApp();
  const [form, setForm] = useState<ProfileData>({name: '', phone: '', address: ''});
  const [consent, setConsent] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(mode === 'edit');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  // 수정 화면은 저장된 값을 불러온다. 이미 동의했던 사람이라 동의 칸도 채운다
  useEffect(() => {
    if (mode !== 'edit') return;
    getProfile().then(p => { if (p) { setForm(p); setConsent(true); } })
      .catch(e => setError(e instanceof Error ? e.message : '회원 정보를 불러오지 못했어요.'))
      .finally(() => setLoading(false));
  }, [mode]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const next = check(form, consent);
    setErrors(next); setMessage(''); setError('');
    if (Object.keys(next).length) return;
    setBusy(true);
    try {
      const saved = await saveProfile({...form, consent});
      setForm(saved); setMessage('저장했어요.'); setProfileComplete(true);
    } catch (err) { setError(err instanceof Error ? err.message : '저장하지 못했어요.'); }
    finally { setBusy(false); }
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
    <div className="consent-box wide">
      <label className="consent-check"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} disabled={busy || loading}/>전체 동의 <span className="req-soft">(필수)</span></label>
      <details className="consent-details">
        <summary>자세히 보기</summary>
        <p><strong>개인정보 수집·이용 동의 (필수)</strong></p>
        <ul>
          <li>수집 항목: 이름, 휴대전화 번호, 주소</li>
          <li>이용 목적: 화물 관련 연락과 본인 확인</li>
          <li>보유 기간: 회원 탈퇴 때까지 (탈퇴하면 바로 지워요)</li>
          <li>동의하지 않아도 되지만, 동의하지 않으면 서비스를 이용할 수 없어요.</li>
        </ul>
      </details>
      {errors.consent && <span className="field-error">{errors.consent}</span>}
    </div>
    <div className="wide profile-actions">
      <button className="button primary" disabled={busy || loading}>{busy ? <LoaderCircle size={15} className="spin"/> : <Check size={15}/>}{mode === 'required' ? '저장하고 시작하기' : '회원 정보 저장하기'}</button>
      <span className="muted"><LockKeyhole size={13}/>암호화해서 저장하고, 운영자에게도 가린 값만 보여요.</span>
    </div>
    {message && <p role="status" className="account-message wide">{message}</p>}
    {error && <p role="alert" className="request-error wide">{error}</p>}
  </form>;

  if (mode === 'edit') return <div className="profile-edit">{loading ? <div className="empty-inline"><LoaderCircle size={16} className="spin"/>불러오는 중</div> : body}</div>;

  return <div className="login-page"><section className="login-card profile-card" aria-labelledby="profile-title">
    <span className="eyebrow"><IdCard size={13}/> 마지막 단계</span>
    <h1 id="profile-title">시작하기 전에<br/>회원 정보를 알려 주세요</h1>
    <p>{user?.email ? <><span className="mono">{user.email}</span> 계정으로 로그인했어요. </> : null}세 칸 모두 필수예요.</p>
    {body}
  </section></div>;
}
