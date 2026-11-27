#!/bin/zsh
cd -- "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
echo "SceneSound 로컬 처리 서버를 시작합니다."
echo "처리와 다운로드가 끝날 때까지 이 창을 켜 두세요."
npm run dev
