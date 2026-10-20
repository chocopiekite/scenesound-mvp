# 씬사운드 MVP

공개 주소: https://scenesound-mvp.vercel.app

저장소: https://github.com/chocopiekite/scenesound-mvp
혼자 영상 만드는 크리에이터를 위한 AI 사운드 어시스턴트.

- 영상 선택 → 장면·사운드 분석 → 실제 CC0 음원 후보 미리 듣기·선택 → 출처 포함 체크리스트 저장
- 이름·연락처·남긴 말 신청 저장 (Supabase)
- 모바일 대응, 가입·결제 없음

## 실행
`npm ci` 후 `npm run dev` → http://127.0.0.1:8001

TwelveLabs 시험 연결을 준비했습니다. 서버 환경 변수 `TWELVELABS_API_KEY`가 필요하며, 선택 설정 `TWELVELABS_MODEL`의 기본값은 `pegasus1.6`입니다. 로컬은 `.env.local`, Vercel은 프로젝트의 비밀 환경 변수에 설정하세요. 키가 없으면 분석 결과를 만들지 않습니다. Free 플랜(월 $0)과 Vercel Production Secret 설정을 확인했습니다. 실제 공개 API 검증 결과는 진행기록.md에 기록합니다.

입력은 1~60초, 3MB 이하 MP4/WebM/MOV이며 가로·세로 각각 360픽셀 이상, 화면 비율은 2.4:1 이내입니다. 영상은 서버를 통해 TwelveLabs 동기 분석 API로 전달하며 씬사운드 서버에는 저장하지 않습니다. 무료 플랜 범위에서 시험하고 유료 업그레이드는 별도 결정합니다.

## 보안
HTML에는 Supabase publishable 키만 포함됩니다. 신청 표는 RLS와 INSERT 전용 권한을 사용해 브라우저 조회·수정·삭제를 막습니다. 마이그레이션은 `supabase/migrations`에 있습니다. 비밀 키와 `.env.local`을 커밋하지 마세요.

## 배포
Vercel Git 연동으로 main push 시 자동 배포합니다. API를 포함하므로 HTML만 별도로 올리지 말고 저장소 전체를 연결하세요.

## 검증
`npm test` — 요청 및 AI 응답 검증. 실제 공개 API 합성 영상 분석(HTTP 200), 브라우저 업로드·추천 3개 표시·선택·목록 저장을 확인했습니다.

수정 후 재배포: `git add . && git commit -m "Update MVP" && git push origin main`

## Freesound 미리 듣기
서버 비밀 변수 `FREESOUND_API_KEY`를 설정하면 추천마다 음원 후보를 최대 3개 검색합니다. CC0만 표시하며 제작자·원본·이용 조건을 함께 제공합니다. 미리 듣기는 Freesound CDN에서 재생하고 원본 다운로드는 Freesound 페이지에서 진행합니다. 원본 영상은 Freesound로 보내지 않고 검색어만 전달합니다.

이번 API 신청은 교육용 MVP 시험 용도입니다. 음원의 CC0 라이선스와 API 이용약관은 별개이며, 상업 서비스 전환 시 Freesound와 API 상업 이용 조건을 확인해야 합니다.
