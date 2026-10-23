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

입력은 1초~10분, 200MB 이하 MP4/WebM/MOV이며 가로·세로 각각 360픽셀 이상, 화면 비율은 2.4:1 이내입니다. 영상은 조각으로 나눠 Supabase Edge Function을 거쳐 TwelveLabs에 업로드합니다. Supabase에는 영상 파일을 저장하지 않습니다. 서버가 서명한 업로드 권한은 전송 대상·조각 크기·1시간 만료를 포함하며, 클라이언트는 API 키를 받지 않습니다. 업로드 완료 후 실제 영상 길이와 용량을 다시 확인하고 TwelveLabs 동기 분석 API에 asset ID로 전달합니다. 분석 종료 시 업로드한 asset 삭제를 요청합니다. 창 닫힘·연결 중단 시 잔여 파일이 생길 수 있으며, 같은 탭에서 다음 분석 시 삭제를 재시도합니다. 만료 이후 남은 asset은 운영자가 TwelveLabs에서 정리해야 합니다. 무료 플랜 범위에서 시험하고 유료 업그레이드는 별도 결정합니다.

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

대용량 전송 설정: `VIDEO_UPLOAD_RELAY_SECRET`을 Vercel Production과 Supabase secrets에 동일한 무작위 값으로 저장합니다. 키는 파일이나 브라우저 코드에 기록하지 않습니다. 전송 함수 배포 명령: `npx supabase functions deploy video-upload --project-ref tyunlhiyvaakxkrubuku --no-verify-jwt --use-api`. JWT 대신 함수 내부에서 HMAC 전송 허가를 검증합니다. Vercel 배포는 main push를 사용합니다.

### Epidemic Sound 로컬 시험 연결
- `npm run dev`로 http://127.0.0.1:8001 을 열면 `전체 / Freesound / Epidemic Sound` 검색을 시험할 수 있습니다. macOS 키체인의 `scenesound-mvp-epidemic-test` 항목에서 키를 메모리로 읽습니다. 키 값은 소스·HTML·기록에 저장하지 않습니다.
- 로컬에 Freesound/TwelveLabs 키가 없으면 기존 공개 MVP의 검색·분석 API로 전달합니다. 영상은 기존과 같이 Supabase 전송 함수를 거쳐 TwelveLabs에 전달됩니다.
- Free API Developer License는 시제품 평가 전용이며 공개 서비스·상용 이용은 허용하지 않습니다. API 키가 잘못 설정되더라도 Vercel 및 루프백 호스트가 아닌 요청에서는 Epidemic Sound API를 사용할 수 없도록 차단합니다. 공개 적용은 별도 계약 확인과 코드 변경 후 진행합니다.
- 효과음 검색 시 두 라이브러리 결과를 합치고 출처·라이선스를 개별 표시합니다. 일부 공급자 오류는 다른 공급자의 결과를 막지 않습니다.
- Epidemic Sound 음원 주소는 미리 듣기 버튼을 누를 때 요청하고 세션에서 재사용합니다. 실제 재생 시 익명 세션 ID와 `trackPreviewed` 이벤트를 서버를 통해 전송합니다. 이름·이메일·영상은 이 검색/재생 API에 전송하지 않습니다.
- 시험 음원은 CC0로 표시하지 않으며 체크리스트에도 시험 이용 조건과 음원 ID를 기록합니다. Free 한도는 계정 포털에서 확인합니다.

### 무료 라이브러리와 다른 후보 찾기
- 공개 사이트는 Freesound와 Wikimedia Commons를 검색합니다. Commons 공식 MediaWiki API를 사용하며, 오디오 파일 중 CC0·퍼블릭 도메인·CC BY 3.0/4.0만 후보로 표시합니다. 작성자·원본·이용 조건을 표시하고 저장 목록에 포함합니다. 발음 자료·권리 제한 표시가 있는 파일·20MB 초과·15분 초과 파일은 제외합니다.
- `↻ 다른 음원 추천받기`는 공급자별 다음 페이지를 조회하고, 이미 보여준 공급자+음원 ID를 제외합니다. 후보 부족·실패 시 현재 후보와 선택한 음원을 보존하며, 새 후보를 받아도 선택은 명시적으로 변경/해제하기 전까지 유지합니다. 최대 50페이지, 요청에 최근 120개 ID까지 포함합니다.
- Pixabay 공식 공개 API는 이미지·영상용으로 안내되고 효과음 검색 API는 확인되지 않았습니다: https://pixabay.com/api/docs/ . K-Sound도 조사한 공식 자료에서 공개 검색 API를 확인하지 못했습니다. 외부 음원을 수집하거나 재호스팅하지 않습니다.
- 각 소리에 `Pixabay·K-Sound에서도 찾아보기`를 제공해 원본 사이트의 검색 결과를 새 탭에서 엽니다. K-Sound 한국어 검색어는 수정 가능하며 로그인·미리 듣기·다운로드·이용 조건 확인은 원본 사이트에서 진행합니다.
- K-Sound 이용 조건: https://www.k-soundlibrary.kr/cop/bbs/selectFaq.do . FAQ에 출처 표기·재배포 제한 등 서로 다른 안내가 있으므로 특정 음원의 사용 조건을 확인해야 합니다.
