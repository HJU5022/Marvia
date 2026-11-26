"use client";
// 로그인 화면 (v1 LoginScreen의 틀). 개발 로그인(토큰 입력)과 구글 로그인 둘 다 auth.ts가 한다.
// [왜] 동작은 그대로다. 모양만 v1의 카드에 입힌다. 오류 글은 role=alert 한 곳에 보인다.
import { CircleAlert, Scale, Ship, Signpost } from "lucide-react";
import { useState } from "react";

import { AUTH_MODE, currentToken, signIn } from "@/lib/auth";

export function LoginScreen({
  error,
  onError,
  onToken,
}: {
  error: string;
  onError: (message: string) => void;
  onToken: (token: string | null) => void;
}) {
  const [devToken, setDevToken] = useState("");
  return (
    <main className="login-page">
      <div className="login-card">
        <h1 className="brand">
          <Ship size={22} aria-hidden="true" />
          Marvia
        </h1>
        <p className="lead">수입 화물을 어떤 단서로든 찾아, 출항부터 반출까지 상태를 그 시점에 유효한 법령과 고시에 맞대어 답해요.</p>
        <ul className="login-points">
          <li>
            <Ship size={16} aria-hidden="true" />
            B/L이나 화물관리번호로 내 화물의 상태를 봐요
          </li>
          <li>
            <Scale size={16} aria-hidden="true" />
            답마다 법령 근거와 시행일을 함께 보여 드려요
          </li>
          <li>
            <Signpost size={16} aria-hidden="true" />
            막히면 다음에 할 일을 제안해요
          </li>
        </ul>
        {error ? (
          <p role="alert" className="notice">
            <CircleAlert size={16} aria-hidden="true" />
            {error}
          </p>
        ) : null}
        {AUTH_MODE === "dev" ? (
          <form
            className="login-form"
            onSubmit={(e) => {
              e.preventDefault();
              signIn(devToken)
                .then(() => currentToken().then(onToken))
                .catch((failure: Error) => onError(failure.message));
            }}
          >
            <label htmlFor="dev-token">개발 로그인 토큰</label>
            <div className="row">
              <input id="dev-token" type="password" value={devToken} onChange={(e) => setDevToken(e.target.value)} />
              <button type="submit">들어가기</button>
            </div>
          </form>
        ) : (
          <button type="button" onClick={() => signIn().catch((failure: Error) => onError(failure.message))}>
            구글로 로그인
          </button>
        )}
      </div>
    </main>
  );
}
