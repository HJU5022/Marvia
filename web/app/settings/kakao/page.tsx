'use client';
/** 카카오 동의 화면이 돌아오는 곳 (/settings/kakao?code=&state= 또는 ?error=). 연결을 마무리하고 /settings?kakao=결과 로 보낸다.
 *
 * 카카오가 서버로 바로 돌아오지 않고 이 화면을 거치는 이유: 이 화면이 로그인 출입증을 붙여 code·state를 서버에 넘겨야, 서버가
 * "연결을 시작한 사람 = 지금 로그인한 사람"을 확인할 수 있다. 서버로 바로 가면 출입증이 없어서, 누군가 자기 연결 링크를 보내 주면
 * 내 카카오톡이 그 사람 계정에 붙을 수 있다. 연결 흐름 전체는 components/KakaoPanel.tsx 첫 설명을 본다.
 *
 * 로그인이 되돌려지기 전에는 서버를 부르지 않는다. 로그인이 켜져 있으면 Shell이 로그인 확인과 회원 정보 확인이 끝나기 전까지 이 화면을 그리지 않고
 * (로그인 뒤에는 같은 주소로 돌아오므로 code·state가 남는다), 여기서도 authReady와 user를 한 번 더 확인한다.
 * 카카오 code는 한 번만 쓸 수 있다. 개발 모드의 StrictMode는 effect를 두 번 돌리므로 ref로 막아 서버를 딱 한 번만 부른다.
 * code·state는 화면에 그리지도, 기록으로 남기지도 않는다.
 */
import {useEffect, useRef} from 'react';
import {useRouter} from 'next/navigation';
import {LoaderCircle} from 'lucide-react';
import {useApp} from '@/components/AppProvider';
import {finishKakaoLink} from '@/lib/api';

export default function KakaoReturnPage() {
  const {authEnabled, authReady, user} = useApp();
  const router = useRouter();
  const started = useRef(false);  // 서버를 부르기 시작했으면 true. 다시 들어와도 부르지 않는다

  useEffect(() => {
    if (started.current) return;
    const params = new URLSearchParams(window.location.search);
    // 동의 화면에서 취소했다: 서버를 부르지 않는다
    if (params.get('error')) { started.current = true; router.replace('/settings?kakao=denied'); return; }
    // 로그인이 되돌려질 때까지 기다린다. 출입증이 없으면 서버가 연결 주인을 확인할 수 없다
    if (!authReady || (authEnabled && !user)) return;
    started.current = true;
    const code = params.get('code'), state = params.get('state');
    if (!code || !state) { router.replace('/settings?kakao=failed'); return; }
    finishKakaoLink(code, state)
      .then(result => router.replace(`/settings?kakao=${encodeURIComponent(result)}`))
      .catch(() => router.replace('/settings?kakao=failed'));
  }, [authEnabled, authReady, user, router]);

  return <div className="page"><p className="muted" role="status"><LoaderCircle size={14} className="spin"/> 카카오톡 연결을 마무리하고 있어요…</p></div>;
}
