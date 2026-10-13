# 씬사운드 MVP

공개 주소: https://scenesound-mvp.vercel.app

저장소: https://github.com/chocopiekite/scenesound-mvp
혼자 영상 만드는 크리에이터를 위한 AI 사운드 어시스턴트.

- 영상 선택 → 장면·사운드 분석 → 추천 체크리스트 저장
- 이름·연락처·남긴 말 신청 저장 (Supabase)
- 모바일 대응, 가입·결제 없음

## 실행
`npm ci` 후 `npm run dev` → http://127.0.0.1:8001

영상 분석은 서버 환경 변수 `GEMINI_API_KEY` 설정이 필요합니다. 로컬은 `.env.local`, Vercel은 프로젝트 환경 변수에 설정하세요. 키가 없으면 연결 준비 안내만 표시하며 분석 결과를 만들지 않습니다.

## 보안
HTML에는 Supabase publishable 키만 포함됩니다. 신청 표는 RLS와 INSERT 전용 권한을 사용해 브라우저 조회·수정·삭제를 막습니다. 마이그레이션은 `supabase/migrations`에 있습니다. 비밀 키와 `.env.local`을 커밋하지 마세요.

## 배포
Vercel Git 연동으로 main push 시 자동 배포합니다. API를 포함하므로 HTML만 별도로 올리지 말고 저장소 전체를 연결하세요.

## 검증
`npm test` — 요청 및 AI 응답 검증. 실제 영상 분석은 API 키 연결 후 검증해야 합니다.

수정 후 재배포: `git add . && git commit -m "Update MVP" && git push origin main`
