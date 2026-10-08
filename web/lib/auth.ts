/** 로그인 (작업 G3 화면 쪽). 구글 로그인은 Supabase Auth가 하고, 화면은 받은 출입증(JWT)을 백엔드에 붙인다.
 *
 * 백엔드 backend/app/auth.py와 짝이다. 그쪽이 SUPABASE_URL로 로그인을 켜고 끄듯, 화면도 두 값이 있을 때만 켠다.
 * - NEXT_PUBLIC_SUPABASE_URL: Supabase 프로젝트 주소 (비밀 아님)
 * - NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: 브라우저용 공개 키 (비밀 아님. service_role/secret 키는 절대 넣지 않는다)
 * 둘 중 하나라도 없으면 로그인 기능이 꺼지고, 화면은 예전처럼 세션 ID로만 돈다 (채점용 compose와 같은 길).
 */
import {createClient, type Session, type SupabaseClient} from '@supabase/supabase-js';

const URL_ = (process.env.NEXT_PUBLIC_SUPABASE_URL ?? '').trim();
const KEY = (process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? '').trim();
export const authEnabled = URL_ !== '' && KEY !== '';

let client: SupabaseClient | null = null;

/** 브라우저에서 처음 쓸 때 한 번만 만든다. 서버 렌더 중에는 만들지 않는다(localStorage가 없다). */
function supabase(): SupabaseClient | null {
  if (!authEnabled || typeof window === 'undefined') return null;
  // 기본 설정: 세션을 localStorage에 두고, 만료 전에 알아서 갱신하고, 구글에서 돌아온 주소의 토큰을 읽는다
  client ??= createClient(URL_, KEY);
  return client;
}

/** 화면에 보여 줄 만큼만. 토큰 원문은 여기 담지 않는다. */
export interface AuthUser { id: string; email: string | null; name: string | null }

function toUser(session: Session | null): AuthUser | null {
  const u = session?.user;
  if (!u) return null;
  const meta = u.user_metadata ?? {};
  return {id: u.id, email: u.email ?? null, name: (meta.full_name ?? meta.name ?? null) as string | null};
}

/** 지금 로그인한 사용자. 로그인이 꺼져 있으면 항상 null. */
export async function currentUser(): Promise<AuthUser | null> {
  const sb = supabase();
  if (!sb) return null;
  const {data} = await sb.auth.getSession();
  return toUser(data.session);
}

/** 로그인·로그아웃·토큰 갱신 때마다 부른다. 해제 함수를 돌려준다. */
export function onAuthChange(callback: (user: AuthUser | null) => void): () => void {
  const sb = supabase();
  if (!sb) return () => {};
  const {data} = sb.auth.onAuthStateChange((_event, session) => callback(toUser(session)));
  return () => data.subscription.unsubscribe();
}

/** 백엔드 요청에 붙일 출입증. getSession은 만료가 가까우면 갱신된 값을 준다. 없으면 null. */
export async function accessToken(): Promise<string | null> {
  const sb = supabase();
  if (!sb) return null;
  const {data} = await sb.auth.getSession();
  return data.session?.access_token ?? null;
}

/** 로그인 뒤 돌아올 주소. 지금 보던 페이지에서 # 뒷부분만 뗀다.
 * Supabase는 돌아올 주소 끝에 #access_token=...을 덧붙인다. 주소에 이미 #이 있으면(/settings#) ##access_token이 되어
 * supabase-js가 "#access_token"이라는 이름으로 읽고 출입증을 못 찾는다(로그인이 안 된 것처럼 보임). 그 상태에서 다시 로그인하면
 * 토큰이 붙은 주소 전체가 돌아올 주소로 넘어가 Supabase 인증 로그에 토큰이 남는다. */
export function returnAddress(loc: Pick<Location, 'origin' | 'pathname' | 'search'>): string {
  return `${loc.origin}${loc.pathname}${loc.search}`;
}

/** 구글 로그인 창으로 보낸다. 끝나면 지금 보던 페이지로 돌아온다. */
export async function signInWithGoogle(): Promise<void> {
  const sb = supabase();
  if (!sb) throw new Error('로그인 기능이 설정되지 않았습니다.');
  const {error} = await sb.auth.signInWithOAuth({provider: 'google', options: {redirectTo: returnAddress(window.location)}});
  if (error) throw new Error('구글 로그인을 시작하지 못했습니다. 잠시 뒤 다시 시도해 주세요.');
}

export async function signOut(): Promise<void> {
  await supabase()?.auth.signOut();
}
