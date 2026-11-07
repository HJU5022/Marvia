# 화면 이미지 (계획 4b Task 8): 의존성 → 빌드 → 실행(standalone, node 사용자). 이미지는 digest로 고정한다
FROM node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d AS deps
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
# [왜] 컨테이너 안에서 npm ci를 한다. 호스트(맥)의 node_modules는 리눅스용 SWC 바이너리가 아니다
RUN npm ci

FROM node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d AS build
WORKDIR /app
# [주의] NEXT_PUBLIC_ 값은 빌드할 때 번들에 박힌다. 주소와 공개 값만 넣는다(토큰·키 금지)
ARG NEXT_PUBLIC_API_URL=http://localhost:8080
ARG NEXT_PUBLIC_AUTH=dev
ARG NEXT_PUBLIC_SUPABASE_URL=
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY=
ENV NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_PUBLIC_AUTH=$NEXT_PUBLIC_AUTH \
    NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
# [왜] 이미지에 있는 node 사용자(uid 1000)로 돈다. 파일 주인은 root라 실행 중에 바꿀 수 없다
USER node
EXPOSE 3000
CMD ["node", "server.js"]
