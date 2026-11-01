# -*- coding: utf-8 -*-
"""
VISIT ONE 확장 기능 (generate.py 에서 호출)
 1) 주간 리포트   /news/weekly/<YYYY-Www>/
 2) 정책·제도     /news/policy/  /news/policy/<id>/   (정책브리핑 정책뉴스 API, 공공누리 1유형만 본문 게재)
 3) 분양가 vs 주변 실거래가  (국토부 아파트 매매 실거래가 API, 카카오 좌표→법정동코드)
 4) 분양 소식 허브 /news/
"""
import os, re, json, time, glob, html as _html, datetime as dt, urllib.request, urllib.parse
import xml.etree.ElementTree as ET

G = None  # generate 모듈 (init 에서 주입)

def init(gen_module):
    global G
    G = gen_module

def _get(url, headers=None, timeout=40):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            print("retry", url.split("?")[0], e); time.sleep(2 + attempt * 3)
    return ""

def _load(name, default):
    try: return json.load(open(os.path.join(G.ROOT, "data", name), encoding="utf-8"))
    except Exception: return default

def _save(name, obj):
    json.dump(obj, open(os.path.join(G.ROOT, "data", name), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

esc = lambda s: _html.escape("" if s is None else str(s), quote=True)

# ═════════════════════════ 3) 실거래가 ═════════════════════════
RTMS = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"

def region_codes(all_h, geo):
    """단지 id → [시군구코드5, 법정동명] (카카오 coord2regioncode, 캐시)"""
    reg = _load("region.json", {})
    key = os.environ.get("KAKAO_REST_KEY")
    if key:
        for h in all_h:
            g = geo.get(h["id"])
            if not g or h["id"] in reg: continue
            u = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json?" + urllib.parse.urlencode({"x": g[1], "y": g[0]})
            t = _get(u, {"Authorization": "KakaoAK " + key})
            try:
                docs = json.loads(t).get("documents") or []
                b = next((d for d in docs if d.get("region_type") == "B"), None)
                if b: reg[h["id"]] = [b["code"][:5], b.get("region_3depth_name") or ""]
            except Exception: pass
            time.sleep(0.03)
        _save("region.json", reg)
    return reg

def fetch_trades(lawd, ym, cache, today):
    """한 달치 거래 (지난달 이전은 확정 → 캐시 재사용)"""
    k = f"{lawd}:{ym}"
    final = ym < (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y%m")
    if final and k in cache: return cache[k]
    key = os.environ.get("APPLYHOME_KEY")
    if not key: return cache.get(k, [])
    out, page = [], 1
    while True:
        t = _get(RTMS + "?" + urllib.parse.urlencode({"serviceKey": key, "LAWD_CD": lawd, "DEAL_YMD": ym, "numOfRows": 1000, "pageNo": page}))
        try: root = ET.fromstring(t)
        except Exception: break
        items = root.findall(".//item")
        for it in items:
            g = lambda n: (it.findtext(n) or "").strip()
            if g("cdealType") in ("O", "Y"): continue          # 해제 거래 제외
            try:
                out.append([g("umdNm"), round(float(g("excluUseAr") or 0), 1), int(g("dealAmount").replace(",", "") or 0), int(g("buildYear") or 0)])
            except Exception: pass
        total = int(root.findtext(".//totalCount") or 0)
        if page * 1000 >= total or not items: break
        page += 1
    cache[k] = out
    time.sleep(0.05)
    return out

def market_compare(all_h, geo, today):
    """대상 단지(아파트, 최근 공고)에 h['mkt'] = [{label, excl, price, avg, n, lo, hi, scope, new_avg, new_n}] 설정"""
    targets = [h for h in all_h if h["cat"] in ("A", "R", "T") and h["types"] and
               (G.status(h)[0] != "마감" or (G.d(h["notice"]) and G.d(h["notice"]) >= today - dt.timedelta(days=120)))]
    if not targets: return
    reg = region_codes(targets, geo)
    cache = _load("trades.json", {})
    months = [(today.replace(day=1) - dt.timedelta(days=31 * i)).strftime("%Y%m") for i in range(12)]
    by_lawd = {}
    for h in targets:
        r = reg.get(h["id"])
        if r: by_lawd.setdefault(r[0], []).append(h)
    for lawd, hs in by_lawd.items():
        trades = []
        for ym in months: trades += fetch_trades(lawd, ym, cache, today)
        for h in hs:
            dong = reg[h["id"]][1]
            rows = []
            for t in h["types"]:
                if not t["excl"] or not t["price"]: continue
                near = lambda tr: abs(tr[1] - t["excl"]) <= 5
                same = [tr for tr in trades if near(tr) and tr[0] == dong]
                scope = f"{dong} 같은 면적대" if len(same) >= 3 else ""
                if not scope:
                    same = [tr for tr in trades if near(tr)]
                    scope = "같은 시·군·구 같은 면적대"
                if len(same) < 3: continue
                ps = sorted(tr[2] for tr in same)
                new = [tr[2] for tr in same if tr[3] and tr[3] >= today.year - 10]
                rows.append(dict(label=t["label"], excl=t["excl"], price=t["price"], avg=int(sum(ps) / len(ps)), n=len(ps),
                                 lo=ps[0], hi=ps[-1], scope=scope, new_avg=int(sum(new) / len(new)) if len(new) >= 3 else 0, new_n=len(new)))
            # 같은 전용 59/84 등 중복 타입은 대표 1개만 (최고가 기준)
            uniq = {}
            for r_ in rows:
                k = int(r_["excl"])
                if k not in uniq or r_["price"] > uniq[k]["price"]: uniq[k] = r_
            if uniq: h["mkt"] = sorted(uniq.values(), key=lambda x: x["excl"])
    # 오래된 캐시 정리(13개월 이전)
    keep = set(months)
    cache = {k: v for k, v in cache.items() if k.split(":")[1] in keep}
    _save("trades.json", cache)

def mkt_box(h):
    rows = h.get("mkt") or []
    if not rows: return ""
    won = G.won
    trs = ""
    for r in rows:
        diff = r["price"] - (r["new_avg"] or r["avg"])
        base = r["new_avg"] or r["avg"]
        pct = diff / base * 100 if base else 0
        tag = (f'<span class="mk-lo">주변 시세보다 약 {won(abs(diff))} 낮음</span>' if pct <= -3 else
               f'<span class="mk-hi">주변 시세보다 약 {won(abs(diff))} 높음</span>' if pct >= 3 else '<span class="mk-eq">주변 시세와 비슷</span>')
        trs += (f'<tr><td><b>{esc(r["label"])}</b><small>{r["excl"]:.0f}㎡</small></td><td class="pr">{won(r["price"])}</td>'
                f'<td>{won(r["avg"])}<small>{r["n"]}건 · {won(r["lo"])}~{won(r["hi"])}</small></td>'
                f'<td>{won(r["new_avg"]) + f"<small>{r["new_n"]}건</small>" if r["new_avg"] else "-"}</td><td>{tag}</td></tr>')
    scope = rows[0]["scope"]
    return (f'<h2>분양가 vs 주변 실거래가</h2><p class="muted">최근 12개월 국토교통부 아파트 매매 실거래가 중 <b>{esc(scope)}</b>(전용 ±5㎡) 거래와 비교했습니다. '
            f'신축 기준은 준공 10년 이내 아파트입니다.</p><div class="tw"><table class="tbl dt mk"><thead><tr><th>타입</th><th>최고 분양가</th>'
            f'<th>주변 평균 실거래가</th><th>신축(10년 이내) 평균</th><th>비교</th></tr></thead><tbody>{trs}</tbody></table></div>'
            f'<p class="muted">※ 실거래가는 층·향·연식에 따라 차이가 크며, 분양가는 타입별 최고가 기준입니다. 단순 참고용으로만 활용하세요. 출처: 국토교통부 실거래가 공개시스템(공공데이터)</p>')

# ═════════════════════════ 2) 정책·제도 ═════════════════════════
POLICY = "https://apis.data.go.kr/1371000/policyNewsService2/policyNewsList2"
POL_MIN = ("국토교통부", "금융위원회", "기획재정부", "재정경제부", "행정안전부", "국무조정실")
POL_RE = re.compile(r"주택|청약|분양|부동산|아파트|공급|전세|월세|임대|택지|재건축|재개발|신도시|주거|대출|DSR|LTV|공공주택|정비사업")

def fetch_policy(today):
    db = _load("policy.json", {})
    key = os.environ.get("APPLYHOME_KEY")
    if key:
        for back in (0, 3, 6):    # 최근 9일 (API는 한 번에 3일까지)
            e = today - dt.timedelta(days=back); s = e - dt.timedelta(days=2)
            t = _get(POLICY + "?" + urllib.parse.urlencode({"serviceKey": key, "startDate": s.strftime("%Y%m%d"), "endDate": e.strftime("%Y%m%d")}))
            try: root = ET.fromstring(t)
            except Exception: continue
            for it in root.iter("NewsItem"):
                g = lambda n: (it.findtext(n) or "").strip()
                nid, title, mins = g("NewsItemId"), g("Title"), g("MinisterCode")
                if not nid or nid in db: continue
                text = title + " " + g("SubTitle1") + " " + re.sub(r"<[^>]+>", " ", g("DataContents"))[:1500]
                if not any(m in mins for m in POL_MIN) or not POL_RE.search(text): continue
                m = re.match(r"(\d{2})/(\d{2})/(\d{4})", g("ApproveDate"))
                date = f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else today.isoformat()
                db[nid] = dict(id=nid, title=title, sub=g("SubTitle1"), body=g("DataContents"), min=mins, date=date,
                               url=g("OriginalUrl"), kogl=g("KoglType"))
            time.sleep(0.2)
        # 최근 400건만 유지
        db = dict(sorted(db.items(), key=lambda kv: kv[1]["date"], reverse=True)[:400])
        _save("policy.json", db)
    return sorted(db.values(), key=lambda x: (x["date"], x["id"]), reverse=True)

def clean_body(htm):
    htm = re.sub(r"(?is)<(script|style|iframe)[^>]*>.*?</\1>", "", htm or "")
    htm = re.sub(r"(?is)<img[^>]*>", "", htm)
    htm = re.sub(r"(?is)<(?!/?(p|br|b|strong|ul|ol|li|table|tr|td|th|thead|tbody|h3|h4)\b)[^>]+>", "", htm)
    htm = re.sub(r'(?i)\s(style|class|id|width|height|align)="[^"]*"', "", htm)
    htm = re.sub(r"(<br\s*/?>\s*){2,}", "<br>", htm)
    return htm.strip()

def plain(htm, n=160):
    t = re.sub(r"<[^>]+>", " ", htm or ""); t = _html.unescape(re.sub(r"\s+", " ", t)).strip()
    return t[:n] + ("…" if len(t) > n else "")

def related_danji(text, all_h):
    """기사 본문에 나온 지역(시군구)과 같은 지역의 진행중 단지 몇 곳"""
    hits = []
    for h in all_h:
        if G.status(h)[0] == "마감": continue
        parts = h["addr"].split()
        sgg = parts[1] if len(parts) > 1 else ""
        key = re.sub(r"(시|군|구)$", "", sgg)
        if len(key) >= 2 and key in text: hits.append(h)
    return hits[:4]

def policy_pages(items, all_h, updated):
    paths = []
    sub = "/news/policy/"
    lis = "".join(f'<li><a href="{sub}{p["id"]}/"><small class="nd">{p["date"]} · {esc(p["min"])}</small><b>{esc(p["title"])}</b><span>{esc(plain(p["sub"] or p["body"], 120))}</span></a></li>' for p in items[:120])
    body = (f'<header class="ph"><p class="cat">POLICY</p><h1>정책·제도 소식</h1><p class="lead">청약·분양·주택 공급·대출 등 부동산 관련 정부 정책 소식을 정책브리핑에서 매일 모아 정리합니다.</p></header>'
            f'<ul class="gl">{lis or "<li class=none>아직 수집된 소식이 없습니다.</li>"}</ul>'
            f'<p class="muted">출처: 대한민국 정책브리핑(www.korea.kr) · 공공누리 제1유형(출처표시) · 데이터 기준일 {updated}</p>')
    paths.append(G.page(G.ROOT, sub, "정책·제도 소식 · 청약·분양·주택 정책", "청약 제도, 주택 공급, 대출 규제 등 부동산 관련 정부 정책 소식을 매일 정리합니다. 출처 정책브리핑.",
                        body, [("분양 소식", "/news/"), ("정책·제도", sub)], [{"@context": "https://schema.org", "@type": "CollectionPage", "name": "정책·제도 소식", "url": G.SITE + sub}], og_type="website", updated=updated))
    for p in items[:150]:
        path = f"{sub}{p['id']}/"
        full = p.get("kogl") in ("1", "제1유형")   # 1유형(출처표시)만 본문 게재
        rel = related_danji(p["title"] + " " + plain(p["body"], 3000), all_h)
        relh = ('<h2>관련 지역 분양 단지</h2><ul class="drs">' + "".join(G.row(h) for h in rel) + "</ul>") if rel else ""
        content = clean_body(p["body"]) if full else f'<p>{esc(plain(p["body"], 400))}</p>'
        body = (f'<article class="guide"><p class="cat">정책·제도 · {esc(p["min"])}</p><h1>{esc(p["title"])}</h1>'
                f'<p class="upd" style="margin:0 0 6px">{p["date"]} · 출처 정책브리핑</p>'
                + (f'<p class="lead">{clean_body(p["sub"])}</p>' if p["sub"] else "")
                + f'<div class="polbody">{content}</div>'
                f'<p class="src muted">이 글은 대한민국 정책브리핑(www.korea.kr)의 기사를 공공누리 제1유형(출처표시)에 따라 게재했습니다. '
                f'<a href="{esc(p["url"])}" target="_blank" rel="noopener">원문 보기 →</a></p>{relh}'
                f'<nav class="pn"><a href="{sub}">← 정책·제도 목록</a><span></span><a href="/bunyang/">전국 분양정보 →</a></nav></article>')
        ld = [{"@context": "https://schema.org", "@type": "NewsArticle", "headline": p["title"][:110], "datePublished": p["date"], "inLanguage": "ko-KR",
               "isBasedOn": p["url"], "publisher": {"@type": "Organization", "name": "VISIT ONE"}, "sourceOrganization": {"@type": "GovernmentOrganization", "name": p["min"] or "대한민국 정부"}}]
        paths.append(G.page(G.ROOT, path, p["title"], plain(p["sub"] or p["body"], 150), body,
                            [("분양 소식", "/news/"), ("정책·제도", sub), (p["title"][:20], path)], ld, updated=updated))
    return paths

# ═════════════════════════ 1) 주간 리포트 ═════════════════════════
def week_info(today):
    mon = today - dt.timedelta(days=today.weekday())
    y, w, _ = mon.isocalendar()
    nth = (mon.day - 1) // 7
    return mon, f"{y}-W{w:02d}", f"{mon.month}월 {('첫째','둘째','셋째','넷째','다섯째')[nth]} 주"

def weekly_report(all_h, policy, updated):
    today = G.TODAY
    mon, wid, wname = week_info(today)
    sun = mon + dt.timedelta(days=6)
    pmon, psun = mon - dt.timedelta(days=7), mon - dt.timedelta(days=1)
    inweek = lambda s, a, b: G.d(s) and a <= G.d(s) <= b
    rcpt = sorted([h for h in all_h if inweek(h["sp_b"] or h["r_b"], mon, sun)], key=lambda h: h["sp_b"] or h["r_b"])
    wins = sorted([h for h in all_h if inweek(h["win"], mon, sun)], key=lambda h: h["win"])
    newn = sorted([h for h in all_h if inweek(h["notice"], pmon, sun) and h["cat"] != "R"], key=lambda h: h["notice"], reverse=True)
    remain = [h for h in rcpt if h["cat"] == "R"]
    top = sorted([h for h in all_h if h.get("rate_all") and inweek(h["r_b"] or h["sp_b"], pmon - dt.timedelta(days=14), psun)],
                 key=lambda h: h["rate_all"], reverse=True)[:10]
    pol = [p for p in policy if G.d(p["date"]) and G.d(p["date"]) >= pmon][:5]
    sido = {}
    for h in rcpt: sido[h["sido"]] = sido.get(h["sido"], 0) + 1
    sido_txt = ", ".join(f"{k} {v}곳" for k, v in sorted(sido.items(), key=lambda kv: -kv[1])[:4])
    title = f"{mon.year}년 {wname} 청약 일정 총정리 — 접수 {len(rcpt)}곳 · 당첨 발표 {len(wins)}곳"
    lead = (f"{mon.month}월 {mon.day}일부터 {sun.month}월 {sun.day}일까지 청약 접수가 시작되는 단지는 {len(rcpt)}곳"
            + (f"({sido_txt})" if sido_txt else "") + f"이고, 당첨자 발표는 {len(wins)}곳입니다."
            + (f" 지난주 청약 결과 가장 경쟁이 치열했던 곳은 {top[0]['name']}({G.cr_txt(top[0]['rate_all'])})입니다." if top else ""))
    def tbl(hs, cols):
        if not hs: return '<p class="none">해당 단지가 없습니다.</p>'
        th = "".join(f"<th>{c[0]}</th>" for c in cols)
        tr = "".join("<tr>" + "".join(f"<td>{c[1](h)}</td>" for c in cols) + "</tr>" for h in hs)
        return f'<div class="tw"><table class="tbl dt"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'
    link = lambda h: f'<a href="/danji/{h["id"]}/"><b>{esc(h["name"])}</b></a>'
    c_rcpt = [("단지", link), ("지역", lambda h: esc(h["sido"])), ("유형", lambda h: esc(G.cat_label(h))), ("접수", lambda h: G.kdate(h["sp_b"] or h["r_b"])),
              ("세대", lambda h: f'{h["units"]:,}'), ("분양가", lambda h: esc(G.price_range(h)) or "-")]
    c_win = [("단지", link), ("지역", lambda h: esc(h["sido"])), ("발표", lambda h: G.kdate(h["win"])), ("계약", lambda h: G.kdate(h["c_b"]))]
    c_top = [("순위", lambda h: str(top.index(h) + 1)), ("단지", link), ("지역", lambda h: esc(h["sido"])), ("경쟁률", lambda h: f'<b class="crt">{G.cr_txt(h["rate_all"])}</b>')]
    c_new = [("단지", link), ("지역", lambda h: esc(h["sido"])), ("공고일", lambda h: G.kdate(h["notice"])), ("접수", lambda h: G.kdate(h["sp_b"] or h["r_b"]))]
    polh = ("".join(f'<li><a href="/news/policy/{p["id"]}/">{esc(p["title"])}</a> <small>{p["date"]} · {esc(p["min"])}</small></li>' for p in pol))
    body = (f'<article class="guide weekly"><p class="cat">WEEKLY REPORT · {wid}</p><h1>{esc(title)}</h1>'
            f'<p class="upd" style="margin:0 0 6px">{mon.isoformat()} ~ {sun.isoformat()} · VISIT ONE 데이터팀 · 업데이트 {updated}</p>'
            f'<p class="lead">{esc(lead)}</p>'
            f'<div class="wk-kpi"><div><b>{len(rcpt)}</b><small>이번 주 청약 접수</small></div><div><b>{len(wins)}</b><small>당첨 발표</small></div>'
            f'<div><b>{len(remain)}</b><small>무순위·잔여</small></div><div><b>{len(newn)}</b><small>새 입주자모집공고</small></div></div>'
            f'<h2>이번 주 청약 접수</h2>{tbl(rcpt, c_rcpt)}'
            f'<h2>이번 주 당첨자 발표</h2>{tbl(wins, c_win)}'
            f'<h2>무순위·잔여세대 (줍줍)</h2>{tbl(remain, c_rcpt)}'
            f'<h2>지난 청약 경쟁률 TOP 10</h2>{tbl(top, c_top)}'
            f'<h2>새로 나온 입주자모집공고</h2>{tbl(newn[:15], c_new)}'
            + (f'<h2>이번 주 정책·제도</h2><ul class="wk-pol">{polh}</ul>' if pol else "")
            + f'<p class="muted src">자료: 한국부동산원 청약홈 공공데이터, 대한민국 정책브리핑. 실제 청약 전에는 반드시 입주자모집공고를 확인하세요.</p>'
            f'<nav class="pn"><a href="/news/weekly/">← 주간 리포트 목록</a><span></span><a href="/calendar/">청약캘린더 →</a></nav></article>')
    path = f"/news/weekly/{wid}/"
    ld = [{"@context": "https://schema.org", "@type": "Article", "headline": title, "datePublished": mon.isoformat(), "dateModified": updated,
           "inLanguage": "ko-KR", "author": {"@type": "Organization", "name": "VISIT ONE"}, "publisher": {"@type": "Organization", "name": "VISIT ONE"}}]
    G.page(G.ROOT, path, title, esc(lead)[:150], body, [("분양 소식", "/news/"), ("주간 리포트", "/news/weekly/"), (wname, path)], ld, updated=updated)
    # 목록 메타 저장
    idx = _load("weekly.json", {})
    idx[wid] = dict(id=wid, title=title, lead=lead, date=mon.isoformat())
    _save("weekly.json", idx)
    reps = sorted(idx.values(), key=lambda x: x["id"], reverse=True)
    lis = "".join(f'<li><a href="/news/weekly/{r["id"]}/"><small class="nd">{r["date"]} 주간</small><b>{esc(r["title"])}</b><span>{esc(r["lead"][:120])}</span></a></li>' for r in reps)
    G.page(G.ROOT, "/news/weekly/", "주간 청약 리포트", "매주 청약 일정, 당첨 발표, 경쟁률 TOP, 무순위 줍줍, 새 공고를 데이터로 정리하는 VISIT ONE 주간 리포트.",
           f'<header class="ph"><p class="cat">WEEKLY</p><h1>주간 청약 리포트</h1><p class="lead">매주 월요일, 그 주의 청약 일정과 지난 청약 결과를 청약홈 데이터로 정리합니다.</p></header><ul class="gl">{lis}</ul>',
           [("분양 소식", "/news/"), ("주간 리포트", "/news/weekly/")], [{"@context": "https://schema.org", "@type": "CollectionPage", "name": "주간 청약 리포트", "url": G.SITE + "/news/weekly/"}], og_type="website", updated=updated)
    return [("/news/weekly/", "0.8", "weekly")] + [(f"/news/weekly/{r['id']}/", "0.7", "weekly") for r in reps], reps

# ═════════════════════════ 4) 분양 소식 허브 ═════════════════════════
def news_hub(reps, policy, updated):
    own = []
    for f in glob.glob(os.path.join(G.ROOT, "news", "*", "index.html")):
        slug = f.split(os.sep)[-2]
        if slug in ("weekly", "policy", "press"): continue
        s = open(f, encoding="utf-8").read()
        t = re.search(r"<h1>(.*?)</h1>", s); dte = re.search(r'"datePublished":\s*"([^"]+)"', s); ds = re.search(r'<meta name="description" content="([^"]*)"', s)
        if t: own.append(dict(slug=slug, title=_html.unescape(re.sub("<[^>]+>", "", t.group(1))), date=(dte.group(1) if dte else ""), desc=_html.unescape(ds.group(1)) if ds else ""))
    own.sort(key=lambda x: x["date"], reverse=True)
    w = "".join(f'<li><a href="/news/weekly/{r["id"]}/"><small class="nd">주간 리포트 · {r["date"]}</small><b>{esc(r["title"])}</b><span>{esc(r["lead"][:110])}</span></a></li>' for r in reps[:4])
    p = "".join(f'<li><a href="/news/policy/{x["id"]}/"><small class="nd">정책·제도 · {x["date"]} · {esc(x["min"])}</small><b>{esc(x["title"])}</b><span>{esc(plain(x["sub"] or x["body"], 110))}</span></a></li>' for x in policy[:8])
    o = "".join(f'<li><a href="/news/{x["slug"]}/"><small class="nd">VISIT ONE · {x["date"]}</small><b>{esc(x["title"])}</b><span>{esc(x["desc"][:110])}</span></a></li>' for x in own)
    body = (f'<header class="ph"><p class="cat">NEWS</p><h1>분양 소식</h1><p class="lead">매주 청약 리포트와 부동산 정책·제도 변화를 한곳에서 확인하세요. 매일 자동으로 업데이트됩니다.</p></header>'
            f'<h2 class="nh">주간 청약 리포트 <a href="/news/weekly/">전체 보기 →</a></h2><ul class="gl">{w}</ul>'
            f'<h2 class="nh">정책·제도 <a href="/news/policy/">전체 보기 →</a></h2><ul class="gl">{p or "<li class=none>수집 중입니다.</li>"}</ul>'
            + (f'<h2 class="nh">VISIT ONE 소식</h2><ul class="gl">{o}</ul>' if o else ""))
    G.page(G.ROOT, "/news/", "분양 소식 · 주간 청약 리포트 · 정책·제도", "매주 청약 일정 리포트와 청약·분양·주택 정책 소식을 매일 업데이트합니다. 비지트원 VISIT ONE 분양 소식.",
           body, [("분양 소식", "/news/")], [{"@context": "https://schema.org", "@type": "CollectionPage", "name": "분양 소식", "url": G.SITE + "/news/"}], og_type="website", updated=updated)
    return [("/news/", "0.8", "daily")]

# ═════════════════════════ 실행 ═════════════════════════
def run(all_h, geo, updated):
    out = []
    policy = []
    try: policy = fetch_policy(G.TODAY)
    except Exception as e: print("policy error", e)
    try: out += policy_pages(policy, all_h, updated)
    except Exception as e: print("policy pages error", e)
    reps = []
    try:
        w, reps = weekly_report(all_h, policy, updated); out += w
    except Exception as e: print("weekly error", e)
    try: out += news_hub(reps, policy, updated)
    except Exception as e: print("hub error", e)
    return [x if isinstance(x, tuple) else (x, "0.6", "monthly") for x in out]
