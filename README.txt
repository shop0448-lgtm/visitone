VISIT ONE 사이트 파일 (visitone.co.kr)

[구성]
index.html          메인 (전체 현장 + 통합 예약)
cheongnyangni/      청량리 시그니처 현장 페이지
glossary/           분양·지역주택조합 용어사전 (허브 + 용어별 페이지)
guide/              분양 가이드 4종
area/dongdaemun/    동대문구·청량리 지역 정보
sitemap.xml         사이트맵 (검색엔진 제출용)
robots.txt          검색 로봇 규칙
llms.txt            AI 검색용 사이트 요약
CNAME, .nojekyll    GitHub Pages 도메인 설정 (지우지 마세요)

[꼭 바꿀 곳] index.html, cheongnyangni/index.html 의 CONFIG
- googleFormLink : 구글폼 "미리 채워진 링크"
- phone, office 등 : 대표번호·주소

[도메인 연결 후]
1) 구글 서치콘솔: 도메인 속성 추가 → 가비아 DNS에 TXT 레코드로 소유 확인 → Sitemaps에 sitemap.xml 제출
2) 네이버 서치어드바이저: 사이트 등록 → HTML 태그 방식 확인코드를 index.html <head>에 추가 → 요청 > 사이트맵 제출
