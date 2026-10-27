# 씬사운드 MVP

## 공개 Studio 연결 (2026-10-27)

- 화면: https://scenesound-mvp.vercel.app/studio.html . 홈페이지의 AAF 초안 버튼으로 진입합니다. 기존 영상 추천·신청 기능도 유지합니다.
- 작업 서버: Render Free, Singapore, Docker (`studio/Dockerfile`). https://scenesound-studio-worker.onrender.com . `/healthz`는 상태 확인용입니다.
- Vercel Secret `STUDIO_WORKER_SECRET`과 Config `STUDIO_WORKER_URL`, Render Secret `STUDIO_WORKER_SECRET` 및 `STUDIO_ALLOWED_ORIGIN`으로 연결합니다. 비밀 값은 문서·소스에 넣지 않습니다.
- Vercel은 HttpOnly/Secure 쿠키로 익명 브라우저 ID를 유지하며 2시간짜리 서명 권한을 발급합니다. Render API는 서명과 작업 소유자를 검사합니다. 음원·결과 미디어는 해당 작업의 1시간짜리 읽기 전용 서명 URL로 제공합니다. 다른 방문자의 작업 조회·변경·삭제는 거절합니다. 회원가입·결제는 없습니다.
- 브라우저는 AAF/연결 오디오/참조 영상을 Render에 직접 업로드합니다. Vercel 요청 본문 한도를 거치지 않습니다. 분석용 영상의 TwelveLabs 업로드는 기존 경로를 유지합니다.
- 무료 서버의 공개 알파 제한: 5분, 영상 200MB, 각 AAF/오디오 100MB, 전체 400MB, 오디오 8트랙·128클립·사용 구간 합계 20분. 한 브라우저 2작업·전체 4작업·렌더 동시 1개. 실제 최대 조합의 부하 검증은 아직 필요합니다.
- 임시 파일은 공개 정적 폴더에 두지 않고 소유자 권한으로 접근합니다. 작업은 24시간 후 주기적으로 정리하며 사용자가 바로 지울 수 있습니다. Render Free는 비활동 시 잠들고 첫 접속이 지연될 수 있습니다. 재시작·재배포 시 파일을 잃을 수 있으므로 결과를 바로 내려받아야 합니다. 영구 보관·가용성을 보장하는 운영 버전이 아닙니다.
- GitHub main push는 Vercel을 자동 배포합니다. Render 공개 Git 저장소 연결은 별도의 수동 배포가 필요할 수 있습니다. 처리 엔진 수정 후 Render에서 최신 커밋 배포도 확인하세요. Vercel CLI 직접 배포는 사용하지 않습니다.
- 생성된 무료 Render 계정에 결제수단·유료 플랜은 추가하지 않았습니다. 공식 무료 플랜 제약: https://render.com/docs/free .

## Studio 자동 처리 알파 (2026-10-26)

새 방향은 대사가 있는 실사 상황극의 **AAF·참조 영상 → 대사 보정과 전체 사운드 배치 → 멀티트랙 수정·내보내기**입니다. 이 절은 10월 26일의 로컬 구현 기록입니다. 이후 공개 연결은 위 10월 27일 안내를 따릅니다.

실행 (macOS, Python 3.9+, Node 20+, FFmpeg/ffprobe 필요):

```sh
python3 -m venv .venv-studio
.venv-studio/bin/python -m pip install -r studio/requirements.txt
npm run dev
```

열기: http://127.0.0.1:8001/studio.html . 기존 추천 화면은 `/`에 있습니다. 현재 컴퓨터의 FFmpeg 8.1.1과 pyaaf2 1.7.1로 확인했습니다.

- AAF: 최상위 Composition 1개, 오디오 트랙 1~24개, 컷(SourceClip)/빈 구간(Filler)/Sequence와 MasterMob 참조 지원. PCM 내장 오디오 또는 사용자가 따로 선택한 연결 오디오. 한 트랙 96클립·전체 256클립·클립 길이 합 60분 이하. 타임라인 Origin 0, 영상 첫 프레임 기준 정렬.
- 입력: 타임라인 10분, 참조 영상 200MB, 개별 AAF/연결 오디오 512MB, 전체 1GB·64파일 이하. 영상은 가로·세로 360픽셀 이상·비율 2.4:1 이내. 로컬 빈 디스크 3GB 이상 필요. 최대 길이·트랙 수 조합의 부하 시험은 미실시.
- 사용자가 대사/기존 소리/제외 역할을 확인합니다. 지정된 AAF 트랙을 섞어 분석용 MP4를 만든 뒤 기존 서명된 Supabase 전송/TwelveLabs 분석을 사용합니다. 참조 영상의 카메라 오디오는 중복해서 넣지 않습니다.
- 대사: 65Hz 고역통과, FFmpeg afftdn의 약한 잡음 감소, 평균 음량 기준 ±6dB 레벨 보정, 완만한 컴프레서·리미터. 대사 전사·화자 분리·심한 클리핑 복원·음악/대사 소스 분리는 미구현. 대사 트랙에 섞인 다른 소리는 함께 처리됩니다.
- 장면 분석의 위치·검색어로 Freesound CC0/Commons 허용 라이선스 음원을 자동 선택합니다. 라이브러리 미리 듣기 파일로 만드는 초안이며 고품질 원본 확보를 보장하지 않습니다. 배경음만 반복하며 효과음은 반복하지 않습니다. 대사 트랙의 실제 신호에 반응해 추가 소리를 덕킹합니다. 사람이 확인할 추천 초안이며 자동 선택·타이밍의 품질 보장은 없습니다.
- 결과: 영상과 동기화된 트랙별 재생·파형·원본 비교, 추가 소리의 시작/끝/음량/사용 여부 수정, 다른 후보로 교체, 실제 재렌더링. 트랙 음량과 사용 여부는 내보내기에도 반영됩니다.
- 출력: 48kHz/16bit 스테레오 WAV 믹스·트랙별 WAV, 소리 입힌 MP4, 내장 PCM AAF와 출처 JSON을 ZIP으로 제공합니다. AAF는 **전체 길이의 렌더된 트랙**이며 원본 클립·플러그인·자동화를 왕복 보존하지 않습니다. 최종 믹스에 버스 리미터가 있어 DAW에서 개별 트랙을 단순 합산한 결과와 피크가 다를 수 있습니다. Pro Tools/Premiere 등 실사용 앱별 호환성은 추가 검증이 필요합니다.
- 로컬 작업은 OS 임시 폴더의 `scenesound-studio/job-UUID`에 저장합니다. UUID를 아는 로컬 브라우저 세션만 접근 가능하며 Host/Origin/교차 사이트 요청을 제한합니다. 수동 삭제와 다음 서버 시작 시 24시간 지난 폴더 정리를 지원합니다. 렌더링 중에는 파일 접근을 막고 성공한 출력만 노출합니다. 서버 재시작 시 남아 있는 완료 작업을 복원합니다. 개인정보를 서버 로그에 남기지 않습니다.
- AAF locator의 원래 경로를 직접 읽지 않습니다. 별도로 올린 오디오의 파일 이름과 대조합니다. FFmpeg의 허용 입력 형식·프로토콜과 음원 다운로드 도메인·크기를 제한합니다. Epidemic 시험용 음원은 자동 렌더링에 사용하지 않습니다.

검증: `npm test` (기존 API+로컬 경계 검사), `npm run test:studio` (실제 FFmpeg/AAF 통합 검사). `studio/test_engine.py --fixture /private/tmp/scenesound-studio-fixture`로 개인 정보 없는 합성 AAF·참조 영상을 만들 수 있습니다. 실제 제작자의 파일을 대신 업로드하지 않습니다.

공개 자동 처리로 전환하려면 별도의 장기 실행 작업 서버·인증·비공개 업로드 저장소·작업 큐·용량 및 이용량 제한을 연결해야 합니다. 현재 로컬 API를 그대로 인터넷에 노출하면 안 됩니다. Vercel CLI 직접 배포나 유료 자원 생성은 진행하지 않았습니다.

참고: [pyaaf2 공식](https://github.com/markreidvfx/pyaaf2), [FFmpeg 필터 문서](https://www.ffmpeg.org/ffmpeg-filters.html).

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

수정 후 재배포: `git add <수정한 파일> && git commit -m "Update MVP" && git push origin main`

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
