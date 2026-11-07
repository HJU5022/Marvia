# Playwright 시험 실행 이미지 (계획 4b Task 9, C9). 브라우저는 이 이미지 안에만 있다(호스트에 설치하지 않는다)
# [주의] 이미지 태그(v1.64.1)와 package.json의 @playwright/test(1.64.1)가 같아야 브라우저 실행 파일을 찾는다
FROM mcr.microsoft.com/playwright:v1.64.1-noble@sha256:2f05f8a734509a7b3f26a912639488ee08f58a7b292d14d62271bcff9038768f
WORKDIR /work
COPY package.json package-lock.json .npmrc ./
RUN npm ci
RUN test "$(node -p "require('@playwright/test/package.json').version")" = "1.64.1"
COPY playwright.config.ts ./
COPY e2e ./e2e
ENV NEXT_TELEMETRY_DISABLED=1
CMD ["npx", "playwright", "test"]
