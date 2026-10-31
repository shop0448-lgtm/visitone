# -*- coding: utf-8 -*-
"""VISIT ONE 공통 페이지 템플릿 (자동 생성 페이지용)"""
import html, json, os

SITE = "https://visitone.co.kr"
esc = lambda s: html.escape("" if s is None else str(s), quote=True)

MARK = ('<svg class="mk" viewBox="0 0 80 100" aria-hidden="true"><path d="M10 96 L10 40 A30 30 0 0 1 70 40 L70 96" fill="none" stroke="currentColor" stroke-width="3"/>'
        '<path d="M50 22 L66 34 L66 96 L50 96 Z" fill="currentColor" fill-opacity=".22"/><path d="M18 44 L32 82 L50 38" fill="none" stroke="currentColor" stroke-width="5"/>'
        '<path d="M50 22 L50 96" fill="none" stroke="currentColor" stroke-width="5"/></svg>')

NAV = ('<a href="/bunyang/">분양정보</a><a href="/map/">분양맵</a><a href="/calendar/">청약캘린더</a><a href="/remain/">무순위·잔여</a>'
       '<a href="/#sites">추천 현장</a><a href="/news/">분양 소식</a><a href="/guide/">가이드</a>')

BIZ = ("상호 제이에이치기획 · 대표 하진훈 · 사업자등록번호 504-28-48757 · 통신판매업 신고 2021-진건퇴계원-278<br>"
       "경기도 남양주시 진건오남로105번길 6, 상가 303 · shop0448@gmail.com")

def page(root, path, title, desc, body, crumbs, jsonld, og_type="article", updated="", extra_css=True, og_image="/img/og.jpg", robots="index,follow,max-image-preview:large"):
    url = SITE + path
    full = [("홈", "/")] + crumbs
    bl = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": SITE + h} for i, (n, h) in enumerate(full)]}
    lds = [bl] + (jsonld or [])
    crumb = " <span>›</span> ".join(f'<a href="{h}">{esc(n)}</a>' if i < len(full) - 1 else f'<span aria-current="page">{esc(n)}</span>' for i, (n, h) in enumerate(full))
    doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
<meta name="theme-color" content="#0c0c0d">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} | VISIT ONE 비지트원</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url}">
<meta name="robots" content="{robots}">
<meta property="og:type" content="{og_type}">
<meta property="og:site_name" content="VISIT ONE 비지트원">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}{og_image}">
<meta property="og:locale" content="ko_KR">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500&family=Noto+Sans+KR:wght@400;500;700&family=Noto+Serif+KR:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/assets/content.css">
<link rel="stylesheet" href="/assets/portal.css">
<link rel="stylesheet" href="/assets/match.css">
<script type="application/ld+json">{json.dumps(lds, ensure_ascii=False)}</script>
</head>
<body>
<header class="hd"><div class="wrap">
<a class="logo" href="/">{MARK}<b>VISIT ONE</b><span>비지트원</span></a>
<nav aria-label="주 메뉴">{NAV}</nav>
<a class="cta" href="/#sites">제휴 현장 예약</a>
</div></header>
<main class="wrap pw">
<nav class="crumb" aria-label="현재 위치">{crumb}</nav>
{body}
</main>
<section class="book"><div class="wrap">
<div><b>VISIT ONE 제휴 현장은 홍보관 방문 예약이 가능합니다</b><p>VISIT ONE이 직접 확인하고 소개하는 현장만 예약을 받습니다. 예약 시간에 전담 상담사가 1:1로 안내합니다.</p></div>
<a href="/#sites">제휴 현장 보기</a>
</div></section>
<footer class="ft"><div class="wrap">
<div class="ftl"><a class="logo" href="/">{MARK}<b>VISIT ONE</b></a><p>전국 분양정보와 청약 일정 · 제휴 현장 홍보관 방문 예약</p></div>
<ul><li><a href="/bunyang/">전국 분양정보</a></li><li><a href="/map/">분양맵</a></li><li><a href="/calendar/">청약캘린더</a></li><li><a href="/remain/">무순위·잔여세대</a></li><li><a href="/glossary/">부동산 용어사전</a></li><li><a href="/service/">서비스 소개</a></li><li><a href="/partner/">현장 입점·제휴 문의</a></li><li><a href="/about/">회사 소개</a></li><li><a href="/privacy/"><b>개인정보처리방침</b></a></li></ul>
<p class="disc">{BIZ}<br><br>분양정보는 한국부동산원 청약홈 공공데이터를 기반으로 하며, 실제 청약 시에는 반드시 청약홈의 입주자모집공고를 확인하세요. 본 사이트는 각 단지의 공식 홈페이지가 아닙니다.{(" 데이터 기준일 " + updated + ".") if updated else ""}</p>
</div></footer>
</body>
</html>
"""
    out = os.path.join(root, path.strip("/"), "index.html") if path != "/" else os.path.join(root, "index.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(doc)
    return path
