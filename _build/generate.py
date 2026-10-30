# -*- coding: utf-8 -*-
"""
VISIT ONE 분양정보 자동 생성기
- 실행: python _build/generate.py            (환경변수 APPLYHOME_KEY 필요, 청약홈 API 호출)
        python _build/generate.py --sample _build/sample.txt   (샘플 데이터로 미리보기)
- 생성: /danji/<id>/, /bunyang/, /bunyang/<지역>/, /calendar/, /remain/, /data/home.json,
        index.html 자동 영역(<!--AUTO:...-->) 갱신, sitemap.xml 병합
"""
import os, sys, json, re, time, shutil, datetime as dt, urllib.request, urllib.parse
sys.path.insert(0, os.path.dirname(__file__))
from tpl import page, esc, SITE

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
KST = dt.timezone(dt.timedelta(hours=9))
TODAY = dt.datetime.now(KST).date()
WINDOW_DAYS = int(os.environ.get("WINDOW_DAYS", "150"))
BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/"
GF = "https://docs.google.com/forms/d/e/1FAIpQLSe6yTNI9B7BjS6nFfUNqKncrnhQ9eGBB2WOrumy7R0FGxmyQA/formResponse"
GFE = {"site": "entry.2052936514", "date": "entry.142109794", "name": "entry.697044918", "phone": "entry.405065089",
       "kind": "entry.1466386561", "memo": "entry.1400009420"}

SIDO = [("서울", "seoul"), ("경기", "gyeonggi"), ("인천", "incheon"), ("부산", "busan"), ("대구", "daegu"), ("광주", "gwangju"),
        ("대전", "daejeon"), ("울산", "ulsan"), ("세종", "sejong"), ("강원", "gangwon"), ("충북", "chungbuk"), ("충남", "chungnam"),
        ("전북", "jeonbuk"), ("전남", "jeonnam"), ("경북", "gyeongbuk"), ("경남", "gyeongnam"), ("제주", "jeju")]
SIDO_SLUG = dict(SIDO)
SPKEYS = [("신혼부부", "NWWDS_HSHLDCO"), ("생애최초", "LFE_FRST_HSHLDCO"), ("다자녀", "MNYCH_HSHLDCO"), ("신생아", "NWBB_HSHLDCO"),
          ("청년", "YGMN_HSHLDCO"), ("노부모부양", "OLD_PARNTS_SUPORT_HSHLDCO"), ("기관추천", "INSTT_RECOMEND_HSHLDCO"),
          ("이전기관", "TRANSR_INSTT_ENFSN_HSHLDCO"), ("기타", "ETC_HSHLDCO")]
REGION_PPY = {}
CATNAME = {"A": "아파트", "O": "오피스텔·도시형", "R": "무순위·잔여세대", "P": "공공지원 민간임대", "T": "임의공급"}

# ───────────────────────── 데이터 수집 ─────────────────────────
def api(endpoint, params):
    key = os.environ["APPLYHOME_KEY"]
    q = urllib.parse.urlencode({**params, "serviceKey": key})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(BASE + endpoint + "?" + q, timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print("retry", endpoint, e); time.sleep(2 + attempt * 3)
    return {"data": []}

def fetch_all(endpoint, since):
    rows, page_no = [], 1
    while True:
        if page_no > 40: break
        r = api(endpoint, {"page": page_no, "perPage": 500, "cond[RCRIT_PBLANC_DE::GTE]": since})
        data = r.get("data") or []
        rows += data
        if len(data) < 500: break
        page_no += 1
    return rows

def fetch_models(endpoint, house_id):
    r = api(endpoint, {"page": 1, "perPage": 200, "cond[HOUSE_MANAGE_NO::EQ]": house_id})
    return r.get("data") or []

def pick(h, *keys):
    for k in keys:
        if h.get(k): return h[k]
    return ""

def norm(cat, h, models):
    t = []
    for m in models:
        if cat in ("A", "R", "T"):
            ty = (m.get("HOUSE_TY") or "").strip()
            excl = to_f(re.sub(r"[^0-9.]", "", ty[:8]))
            label = f"{int(excl)}{re.sub(r'[0-9. ]', '', ty)}" if excl else ty
            sp = {nm: to_i(m.get(k)) for nm, k in SPKEYS if to_i(m.get(k))}
            t.append(dict(label=label, excl=excl, sup=to_f(m.get("SUPLY_AR")), price=to_i(m.get("LTTOT_TOP_AMOUNT")),
                          units=to_i(m.get("SUPLY_HSHLDCO")) + to_i(m.get("SPSPLY_HSHLDCO")),
                          gen=to_i(m.get("SUPLY_HSHLDCO")), sps=to_i(m.get("SPSPLY_HSHLDCO")), sp=sp))
        else:
            t.append(dict(label=(m.get("TP") or "").strip(), excl=to_f(m.get("EXCLUSE_AR")), sup=0,
                          price=to_i(m.get("SUPLY_AMOUNT")), units=to_i(m.get("SUPLY_HSHLDCO"))))
    return dict(
        cat=cat, id=str(h.get("HOUSE_MANAGE_NO")), pblanc=str(h.get("PBLANC_NO") or h.get("HOUSE_MANAGE_NO")),
        name=(h.get("HOUSE_NM") or "").strip(), sido=(h.get("SUBSCRPT_AREA_CODE_NM") or "").strip(),
        addr=(h.get("HSSPLY_ADRES") or "").strip(), units=to_i(h.get("TOT_SUPLY_HSHLDCO")),
        notice=pick(h, "RCRIT_PBLANC_DE"), sp_b=pick(h, "SPSPLY_RCEPT_BGNDE"), sp_e=pick(h, "SPSPLY_RCEPT_ENDDE"),
        r_b=pick(h, "GNRL_RNK1_CRSPAREA_RCPTDE", "SUBSCRPT_RCEPT_BGNDE", "GNRL_RCEPT_BGNDE"),
        r_e=pick(h, "GNRL_RNK2_CRSPAREA_ENDDE", "GNRL_RNK1_CRSPAREA_ENDDE", "SUBSCRPT_RCEPT_ENDDE", "GNRL_RCEPT_ENDDE"),
        win=pick(h, "PRZWNER_PRESNATN_DE"), c_b=pick(h, "CNTRCT_CNCLS_BGNDE"), c_e=pick(h, "CNTRCT_CNCLS_ENDDE"),
        move=pick(h, "MVN_PREARNGE_YM"), cnst=(h.get("CNSTRCT_ENTRPS_NM") or "").strip(), bsns=(h.get("BSNS_MBY_NM") or "").strip(),
        tel=(h.get("MDHS_TELNO") or "").strip(), dtl=pick(h, "HOUSE_DTL_SECD_NM", "HOUSE_DETAIL_SECD_NM", "HOUSE_SECD_NM"),
        cap=h.get("PARCPRC_ULS_AT") == "Y", spec=h.get("SPECLT_RDN_EARTH_AT") == "Y", adj=h.get("MDAT_TRGET_AREA_SECD") == "Y",
        home=(h.get("HMPG_ADRES") or "").strip(), url=(h.get("PBLANC_URL") or "").strip(), types=t)

def to_i(v):
    try: return int(float(str(v).replace(",", "")))
    except Exception: return 0

def to_f(v):
    try: return float(str(v).replace(",", "").strip())
    except Exception: return 0.0

def load_live():
    since = (TODAY - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    spec = [("A", "getAPTLttotPblancDetail", "getAPTLttotPblancMdl"),
            ("O", "getUrbtyOfctlLttotPblancDetail", "getUrbtyOfctlLttotPblancMdl"),
            ("R", "getRemndrLttotPblancDetail", "getRemndrLttotPblancMdl"),
            ("P", "getPblPvtRentLttotPblancDetail", "getPblPvtRentLttotPblancMdl"),
            ("T", "getOPTLttotPblancDetail", "getOPTLttotPblancMdl")]
    out = []
    for cat, det, mdl in spec:
        rows = fetch_all(det, since)
        print(cat, len(rows), "rows")
        for h in rows:
            out.append(norm(cat, h, fetch_models(mdl, h.get("HOUSE_MANAGE_NO"))))
            time.sleep(0.05)
    return out

def load_sample(path):
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line: continue
        p = line.split("|")
        cat, hid, name, sido, addr, units, notice, sp_b, sp_e, r_b, r_e, win, c_b, c_e, move, cnst, bsns, tel, dtl, cap, spec, adj, home, ty = p[:24]
        types = []
        for t in filter(None, ty.split(";")):
            a = t.split("-")
            if cat == "O":
                types.append(dict(label=a[0], excl=to_f(a[1]), sup=0, price=to_i(a[2]), units=to_i(a[3])))
            else:
                excl = to_f(re.sub(r"[^0-9.]", "", a[0]))
                types.append(dict(label=f"{int(excl)}{re.sub(r'[0-9. ]', '', a[0])}", excl=excl, sup=to_f(a[1]), price=to_i(a[2]), units=to_i(a[3])))
        url = (f"https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo={hid}&pblancNo={hid}" if cat == "A"
               else "https://www.applyhome.co.kr/")
        out.append(dict(cat=cat, id=hid, pblanc=hid, name=name, sido=sido, addr=addr, units=to_i(units), notice=notice, sp_b=sp_b, sp_e=sp_e,
                        r_b=r_b, r_e=r_e, win=win, c_b=c_b, c_e=c_e, move=move, cnst=cnst, bsns=bsns, tel=tel, dtl=dtl,
                        cap=cap == "Y", spec=spec == "Y", adj=adj == "Y", home=("https://" + home) if home and not home.startswith("http") else home,
                        url=url, types=types))
    return out

# ───────────────────────── 계산 도우미 ─────────────────────────
def d(s):
    try: return dt.date.fromisoformat(s[:10])
    except Exception: return None

def status(h):
    rb, re_, win, cb, ce = d(h["sp_b"]) or d(h["r_b"]), d(h["r_e"]) or d(h["r_b"]), d(h["win"]), d(h["c_b"]), d(h["c_e"]) or d(h["c_b"])
    if rb and TODAY < rb: return ("예정", f"접수 D-{(rb - TODAY).days}")
    if rb and re_ and rb <= TODAY <= re_: return ("접수중", "청약 접수중")
    if win and TODAY < win: return ("발표대기", "당첨 발표 대기")
    if cb and TODAY < cb: return ("계약예정", "계약 예정")
    if cb and ce and cb <= TODAY <= ce: return ("계약중", "계약 진행중")
    return ("마감", "청약 마감")

def won(m):
    if not m: return "-"
    e, r = divmod(int(m), 10000)
    if e and r: return f"{e}억 {r:,}만"
    if e: return f"{e}억"
    return f"{r:,}만"

def py(a): return f"{a * 0.3025:.1f}"

def tel_fmt(t):
    t = re.sub(r"\D", "", t or "")
    if len(t) == 8: return f"{t[:4]}-{t[4:]}"
    if t.startswith("02") and len(t) in (9, 10): return f"02-{t[2:-4]}-{t[-4:]}"
    if len(t) in (10, 11): return f"{t[:3]}-{t[3:-4]}-{t[-4:]}"
    return t

def kdate(s):
    x = d(s)
    if not x: return "-"
    return f"{x.month}.{x.day}({'월화수목금토일'[x.weekday()]})"

def price_range(h):
    ps = [t["price"] for t in h["types"] if t["price"]]
    if not ps: return ""
    lo, hi = min(ps), max(ps)
    return won(lo) if lo == hi else f"{won(lo)} ~ {won(hi)}"

def short_addr(a):
    parts = a.split()
    return " ".join(parts[:3]) if parts else ""

def cat_label(h):
    if h["cat"] == "O" and h["dtl"] and "/" not in h["dtl"]: return h["dtl"]
    if h["cat"] == "R" and h["dtl"]: return h["dtl"] if h["dtl"] in ("무순위", "불법행위 재공급", "계약취소주택") else "무순위·잔여"
    return CATNAME.get(h["cat"], "")

def ppy_of(h):
    """평당 분양가(만원, 공급면적 기준, 타입별 최고가의 중앙값)"""
    v = sorted(t["price"] / (t["sup"] * 0.3025) for t in h["types"] if t["price"] and t["sup"])
    return int(v[len(v) // 2]) if v else 0

def sp_total(h):
    out = {}
    for t in h["types"]:
        for k, v in (t.get("sp") or {}).items(): out[k] = out.get(k, 0) + v
    return out

def faq(h):
    q = []
    nm = h["name"]
    sched = []
    if h["sp_b"]: sched.append(f'특별공급 접수 {h["sp_b"]}')
    if h["r_b"]: sched.append(f'{"일반공급" if h["cat"] == "A" else "청약"} 접수 {h["r_b"]}' + (f' ~ {h["r_e"]}' if h["r_e"] and h["r_e"] != h["r_b"] else ""))
    if h["win"]: sched.append(f'당첨자 발표 {h["win"]}')
    if h["c_b"]: sched.append(f'계약 {h["c_b"]}' + (f' ~ {h["c_e"]}' if h["c_e"] and h["c_e"] != h["c_b"] else ""))
    if sched: q.append((f"{nm} 청약 일정은 어떻게 되나요?", " · ".join(sched) + " 일정입니다. 입주자모집공고는 " + h["notice"] + "에 게시되었습니다."))
    pr = price_range(h)
    if pr:
        a = f"타입별 최고 분양가 기준 {pr}입니다."
        pp = ppy_of(h)
        if pp: a += f" 공급면적 3.3㎡(평)당 약 {pp:,}만 원 수준입니다."
        q.append((f"{nm} 분양가는 얼마인가요?", a + " 층·호별 정확한 금액은 입주자모집공고에서 확인하세요."))
    if h["types"]:
        ts = ", ".join(f'{t["label"]}(전용 {t["excl"]:.0f}㎡)' for t in h["types"][:8])
        q.append((f"{nm}에는 어떤 타입이 있나요?", f"{ts} 등 {len(h['types'])}개 타입, 총 {h['units']:,}세대가 공급됩니다."))
    spt = sp_total(h)
    if spt:
        q.append((f"{nm} 특별공급은 몇 세대인가요?", " · ".join(f"{k} {v}세대" for k, v in spt.items()) + "입니다. 유형별 자격 요건은 공고문을 확인하세요."))
    if h["cat"] in ("R",):
        q.append(("청약통장이 없어도 신청할 수 있나요?", "무순위·잔여세대 청약은 일반적으로 청약통장이 필요하지 않습니다. 다만 무주택 여부, 거주 지역 등 신청 자격은 단지별 공고에 따라 다르니 반드시 확인하세요."))
    elif h["cat"] == "O":
        q.append(("청약통장이 없어도 신청할 수 있나요?", "오피스텔·도시형생활주택 청약은 일반적으로 청약통장 없이 신청할 수 있습니다. 세부 자격과 전매 조건은 공고문을 확인하세요."))
    elif h["cat"] == "A":
        q.append(("청약통장이 꼭 있어야 하나요?", "아파트 특별공급·일반공급은 청약통장 가입 기간과 예치금 요건을 충족해야 합니다. 통장이 없다면 무순위·잔여세대나 오피스텔 청약을 함께 살펴보세요."))
    if h["cnst"]: q.append((f"{nm} 시공사는 어디인가요?", f"시공사는 {h['cnst']}" + (f", 시행사는 {h['bsns']}입니다." if h["bsns"] else "입니다.")))
    if len(h["move"]) >= 6: q.append((f"{nm} 입주는 언제인가요?", f"입주 예정 시기는 {h['move'][:4]}년 {int(h['move'][4:6])}월입니다. 공정에 따라 달라질 수 있습니다."))
    reg = [t for t, on in (("분양가상한제", h["cap"]), ("투기과열지구", h["spec"]), ("조정대상지역", h["adj"])) if on]
    if reg: q.append(("규제 지역에 해당하나요?", f"{', '.join(reg)} 적용 단지입니다. 전매제한, 재당첨 제한, 거주의무 등이 적용될 수 있으니 공고문에서 확인하세요."))
    return q

# ───────────────────────── 화면 조각 ─────────────────────────
def badge(h):
    st, txt = status(h)
    return f'<span class="st st-{st}">{esc(txt)}</span>'

def row(h):
    return (f'<li class="dr" data-s="{esc(h["sido"])}" data-c="{h["cat"]}" data-st="{status(h)[0]}" data-k="{esc(h["name"] + " " + h["addr"])}" data-id="{h["id"]}">'
            f'<a href="/danji/{h["id"]}/"><div class="dr-top">{badge(h)}<small>{esc(cat_label(h))} · {esc(h["sido"])}</small></div>'
            f'<b>{esc(h["name"])}</b><p>{esc(short_addr(h["addr"]))} · {h["units"]:,}세대</p>'
            f'<div class="dr-meta"><span>접수 {kdate(h["sp_b"] or h["r_b"])}</span><span>발표 {kdate(h["win"])}</span>'
            + (f'<span class="pr">{esc(price_range(h))}</span>' if price_range(h) else "") + '</div></a></li>')

def consult_form(h):
    return f"""<section class="consult" id="consult"><h2>이 단지 상담 신청</h2>
<p>청약 자격, 자금 계획, 비슷한 조건의 VISIT ONE 추천 현장까지 상담사가 연락드려 안내해 드립니다.</p>
<form class="pform" id="cform" novalidate><div class="pgrid">
<label>성함 *<input id="c_name" autocomplete="name"></label>
<label>연락처 *<input id="c_phone" type="tel" inputmode="numeric" placeholder="010-0000-0000"></label></div>
<label>문의 내용<textarea id="c_memo" rows="3" placeholder="관심 타입, 궁금한 점 등을 남겨 주세요."></textarea></label>
<label class="pagree"><input type="checkbox" id="c_agree"> [필수] 분양 상담 안내를 위한 개인정보(성함, 연락처) 수집·이용에 동의합니다. 보유 기간: 상담 완료 후 1년. <a href="/privacy/">처리방침</a></label>
<p class="perr" id="c_err" hidden>성함, 연락처를 입력하고 동의에 체크해 주세요.</p>
<button type="submit" class="pbtn">상담 신청하기</button><p class="pok" id="c_ok" hidden>신청이 접수되었습니다. 확인 후 연락드리겠습니다.</p></form>
<script>(function(){{var f=document.getElementById('cform'),v=function(i){{return document.getElementById(i).value.trim();}};
document.getElementById('c_phone').addEventListener('input',function(e){{var x=e.target.value.replace(/[^0-9]/g,'').slice(0,11);if(x.length>7)x=x.replace(/(\\d{{3}})(\\d{{3,4}})(\\d{{4}})/,'$1-$2-$3');else if(x.length>3)x=x.slice(0,3)+'-'+x.slice(3);e.target.value=x;}});
f.addEventListener('submit',function(e){{e.preventDefault();var ok=v('c_name')&&/^0\\d{{1,2}}-?\\d{{3,4}}-?\\d{{4}}$/.test(v('c_phone'))&&document.getElementById('c_agree').checked;
document.getElementById('c_err').hidden=ok;if(!ok)return;var b=new URLSearchParams();
b.append('{GFE["site"]}','[단지문의] {esc(h["name"]).replace("'", "")}');b.append('{GFE["date"]}','단지문의');b.append('{GFE["name"]}',v('c_name'));b.append('{GFE["phone"]}',v('c_phone'));b.append('{GFE["kind"]}','{h["id"]}');b.append('{GFE["memo"]}',v('c_memo'));
fetch('{GF}',{{method:'POST',mode:'no-cors',body:b}}).then(function(){{f.querySelector('.pbtn').disabled=true;document.getElementById('c_ok').hidden=false;}}).catch(function(){{document.getElementById('c_err').textContent='전송에 실패했습니다. 잠시 후 다시 시도해 주세요.';document.getElementById('c_err').hidden=false;}});}});}})();</script></section>"""

def price_box(h):
    pp = ppy_of(h)
    if not pp: return ""
    avg = REGION_PPY.get(h["sido"], (0, 0))
    cmp = ""
    if avg[0] and avg[1] >= 2:
        diff = (pp - avg[0]) / avg[0] * 100
        mx = max(pp, avg[0]) * 1.1
        word = "비슷한" if abs(diff) < 3 else (f"{abs(diff):.0f}% 낮은" if diff < 0 else f"{abs(diff):.0f}% 높은")
        cmp = (f'<p class="pa-say">최근 {esc(h["sido"])} 분양 단지 평균보다 <b>{word}</b> 수준입니다.</p>'
               f'<div class="bars"><div><span>이 단지</span><i style="width:{pp / mx * 100:.0f}%"></i><b>{pp:,}만</b></div>'
               f'<div><span>{esc(h["sido"])} 평균</span><i class="g" style="width:{avg[0] / mx * 100:.0f}%"></i><b>{avg[0]:,}만</b></div></div>'
               f'<p class="muted">※ 최근 {WINDOW_DAYS}일 공고 기준 {esc(h["sido"])} 아파트 {avg[1]}개 단지의 평균, 타입별 최고가·공급면적 기준 단순 계산값입니다.</p>')
    return f'<h2>분양가 분석</h2><div class="pa"><div class="pa-n"><small>3.3㎡(평)당 분양가</small><b>{pp:,}<em>만 원</em></b></div><div class="pa-c">{cmp or "<p class=muted>비교할 같은 지역 단지가 아직 충분하지 않습니다.</p>"}</div></div>'

def sp_box(h):
    rows = [t for t in h["types"] if t.get("sp")]
    if not rows: return ""
    keys = [k for k, _ in SPKEYS if any(k in t["sp"] for t in rows)]
    head = "".join(f"<th>{k}</th>" for k in keys)
    trs = "".join(f'<tr><td><b>{esc(t["label"])}</b></td>' + "".join(f'<td>{t["sp"].get(k, 0) or "-"}</td>' for k in keys) + f'<td><b>{t.get("sps", 0)}</b></td><td>{t.get("gen", 0)}</td></tr>' for t in h["types"])
    return f'<h2>특별공급 유형별 세대수</h2><div class="tw"><table class="tbl dt sp"><thead><tr><th>타입</th>{head}<th>특공 계</th><th>일반공급</th></tr></thead><tbody>{trs}</tbody></table></div>'

def danji_page(h, all_h, updated):
    st, st_txt = status(h)
    steps = [("모집공고", h["notice"]), ("특별공급", h["sp_b"]), ("청약 접수", h["r_b"]), ("당첨 발표", h["win"]), ("계약", h["c_b"])]
    tl = "".join(f'<li class="{"done" if d(v) and d(v) < TODAY else ("now" if d(v) == TODAY else "")}"><b>{lbl}</b><span>{kdate(v) if v else "-"}</span></li>' for lbl, v in steps if v or lbl in ("모집공고", "당첨 발표"))
    flags = "".join(f'<span class="fl">{t}</span>' for t, on in (("분양가상한제", h["cap"]), ("투기과열지구", h["spec"]), ("조정대상지역", h["adj"])) if on)
    if h["types"]:
        trs = "".join(f'<tr><td><b>{esc(t["label"])}</b></td><td>{t["excl"]:.2f}㎡<small>{py(t["excl"])}평</small></td>'
                      f'<td>{(f"{t["sup"]:.2f}㎡<small>{py(t["sup"])}평</small>") if t["sup"] else "-"}</td><td>{t["units"]:,}</td><td class="pr">{won(t["price"])}</td></tr>' for t in h["types"])
        ttable = f'<div class="tw"><table class="tbl dt"><thead><tr><th>타입</th><th>전용</th><th>공급</th><th>공급세대</th><th>최고 분양가</th></tr></thead><tbody>{trs}</tbody></table></div><p class="muted">※ 분양가는 타입별 최고가 기준입니다. 층·호별 금액은 입주자모집공고를 확인하세요.</p>'
    else:
        ttable = '<p class="muted">타입별 공급 정보는 청약홈 입주자모집공고에서 확인하실 수 있습니다.</p>'
    info = [("공급 위치", h["addr"]), ("공급 규모", f'{h["units"]:,}세대'), ("주택 구분", cat_label(h) + (f' ({h["dtl"]})' if h["cat"] == "A" and h["dtl"] else "")),
            ("시공사", h["cnst"]), ("시행사", h["bsns"]), ("입주 예정", f'{h["move"][:4]}년 {int(h["move"][4:6])}월' if len(h["move"]) >= 6 else h["move"]),
            ("문의", tel_fmt(h["tel"]))]
    info_html = "".join(f"<tr><th>{k}</th><td>{esc(v)}</td></tr>" for k, v in info if v and v.strip() not in ("", "-"))
    links = []
    if h["url"]: links.append(f'<a class="lb" href="{esc(h["url"])}" target="_blank" rel="noopener nofollow">청약홈 입주자모집공고 보기 →</a>')
    if h["home"]: links.append(f'<a class="lb ghost" href="{esc(h["home"])}" target="_blank" rel="noopener nofollow">분양 홈페이지 →</a>')
    same = [x for x in all_h if x["sido"] == h["sido"] and x["id"] != h["id"]][:6]
    rel = ('<h2>같은 지역 분양 단지</h2><ul class="drs">' + "".join(row(x) for x in same) + f'</ul><p><a href="/bunyang/{SIDO_SLUG.get(h["sido"], "")}/">{esc(h["sido"])} 분양 전체 보기 →</a></p>') if same else ""
    fq = faq(h)
    faq_html = ('<section class="faq"><h2>자주 묻는 질문</h2>' + "".join(f'<details><summary>{esc(a)}</summary><p>{esc(b)}</p></details>' for a, b in fq) + '</section>') if fq else ""
    pr = price_range(h)
    lead = f'{esc(h["addr"])}에 공급되는 {h["units"]:,}세대 규모의 {esc(cat_label(h))}입니다.' + (f' 타입별 최고 분양가는 {esc(pr)} 수준입니다.' if pr else "")
    body = f"""<article class="danji">
<div class="dh"><div class="dh-tags">{badge(h)}<span class="cat">{esc(cat_label(h))}</span><span class="cat">{esc(h["sido"])}</span>{flags}</div>
<h1>{esc(h["name"])}</h1><p class="lead">{lead}</p>
<div class="kf"><div><small>공급 세대</small><b>{h["units"]:,}세대</b></div><div><small>청약 접수</small><b>{kdate(h["sp_b"] or h["r_b"])}</b></div><div><small>당첨 발표</small><b>{kdate(h["win"])}</b></div><div><small>분양가</small><b>{esc(pr) if pr else "공고 확인"}</b></div></div>
<div class="dh-cta">{"".join(links)}<a class="lb gold" href="#consult">상담 신청</a></div></div>
<h2>청약 일정</h2><ol class="tline">{tl}</ol>
<table class="tbl sched"><tbody>
<tr><th>입주자모집공고</th><td>{esc(h["notice"])}</td></tr>
{f'<tr><th>특별공급 접수</th><td>{esc(h["sp_b"])}{(" ~ " + esc(h["sp_e"])) if h["sp_e"] and h["sp_e"] != h["sp_b"] else ""}</td></tr>' if h["sp_b"] else ""}
<tr><th>{"일반공급 접수" if h["cat"] == "A" else "청약 접수"}</th><td>{esc(h["r_b"])}{(" ~ " + esc(h["r_e"])) if h["r_e"] and h["r_e"] != h["r_b"] else ""}</td></tr>
<tr><th>당첨자 발표</th><td>{esc(h["win"])}</td></tr>
<tr><th>계약</th><td>{esc(h["c_b"])}{(" ~ " + esc(h["c_e"])) if h["c_e"] and h["c_e"] != h["c_b"] else ""}</td></tr>
</tbody></table>
<h2>타입별 공급 정보</h2>{ttable}
{price_box(h)}{sp_box(h)}
<h2>단지 정보</h2><table class="tbl"><tbody>{info_html}</tbody></table>
{consult_form(h)}
{faq_html}
{rel}
<p class="muted src">출처: 한국부동산원 청약홈 분양정보(공공데이터). 데이터 기준일 {updated}. 본 페이지는 정보 제공용이며 해당 단지의 공식 홈페이지가 아닙니다. 청약 전 반드시 청약홈의 입주자모집공고를 확인하세요.</p>
</article>"""
    desc = f'{h["name"]} 청약 일정, 분양가, 타입별 공급 정보. {short_addr(h["addr"])} {h["units"]:,}세대 · 접수 {h["sp_b"] or h["r_b"]} · 당첨 발표 {h["win"]}.'
    ld = [{"@context": "https://schema.org", "@type": "ApartmentComplex", "name": h["name"], "url": f"{SITE}/danji/{h['id']}/",
           "description": desc, "numberOfAccommodationUnits": h["units"],
           "address": {"@type": "PostalAddress", "streetAddress": h["addr"], "addressRegion": h["sido"], "addressCountry": "KR"}}]
    if fq: ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": a, "acceptedAnswer": {"@type": "Answer", "text": b}} for a, b in fq]})
    sl = SIDO_SLUG.get(h["sido"], "")
    crumbs = [("분양정보", "/bunyang/")] + ([(h["sido"], f"/bunyang/{sl}/")] if sl else []) + [(h["name"], f"/danji/{h['id']}/")]
    return page(ROOT, f"/danji/{h['id']}/", f"{h['name']} 분양정보·청약일정", desc, body, crumbs, ld, updated=updated)

def list_page(path, title, desc, intro, items, crumbs, updated, filters=True):
    chips = ""
    if filters:
        sido_counts = {}
        for h in items: sido_counts[h["sido"]] = sido_counts.get(h["sido"], 0) + 1
        chips = ('<div class="flt"><div class="chips" id="fs"><button type="button" class="on" data-v="">전체 지역</button>'
                 + "".join(f'<button type="button" data-v="{esc(s)}">{esc(s)} <i>{sido_counts[s]}</i></button>' for s, _ in SIDO if s in sido_counts) + '</div>'
                 '<div class="chips" id="fc"><button type="button" class="on" data-v="">전체 유형</button><button type="button" data-v="A">아파트</button><button type="button" data-v="O">오피스텔·도시형</button><button type="button" data-v="R">무순위·잔여</button><button type="button" data-v="P">공공지원 민간임대</button></div>'
                 '<div class="chips" id="ft"><button type="button" class="on" data-v="">전체 상태</button><button type="button" data-v="예정">접수 예정</button><button type="button" data-v="접수중">접수중</button><button type="button" data-v="발표대기">발표 대기</button><button type="button" data-v="계약중">계약중</button></div>'
                 '<label class="search"><span>단지 검색</span><input id="fq" type="search" placeholder="단지명·지역 입력"></label></div>')
    js = """<script>(function(){var st={s:'',c:'',t:'',q:''};var q0=new URLSearchParams(location.search).get('q');var qi=document.getElementById('fq');if(q0&&qi){qi.value=q0;st.q=q0;}
function ap(){var n=0;document.querySelectorAll('.drs .dr').forEach(function(li){var ok=!li.classList.contains('nf')&&(!st.s||li.dataset.s===st.s)&&(!st.c||li.dataset.c===st.c)&&(!st.t||li.dataset.st===st.t)&&(!st.q||li.dataset.k.toLowerCase().indexOf(st.q.toLowerCase())>-1);li.hidden=!ok;if(ok)n++;});var c=document.getElementById('cnt');if(c)c.textContent=n;}
[['fs','s'],['fc','c'],['ft','t']].forEach(function(p){var g=document.getElementById(p[0]);if(!g)return;g.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;g.querySelectorAll('button').forEach(function(x){x.classList.toggle('on',x===b);});st[p[1]]=b.dataset.v;ap();});});
if(qi)qi.addEventListener('input',function(){st.q=qi.value.trim();ap();});window.addEventListener('vo-filter',ap);ap();})();</script><script src="/assets/match.js" defer></script>""" if filters else ""
    body = (f'<header class="ph"><p class="cat">BUNYANG</p><h1>{esc(title)}</h1><p class="lead">{intro}</p></header>{chips}' +
            ('<div class="fitbar" id="fitbar"><span class="fb-sum"></span><button type="button" class="fb-toggle" hidden>내 조건만 보기</button><button type="button" class="fb-set">내 조건 설정</button></div>' if filters else "") + f'<p class="cntline"><b id="cnt">{len(items)}</b>개 단지 · 데이터 기준일 {updated}</p><ul class="drs">' + "".join(row(h) for h in items) + "</ul>" + js)
    ld = [{"@context": "https://schema.org", "@type": "ItemList", "name": title, "numberOfItems": len(items),
           "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": f"{SITE}/danji/{h['id']}/", "name": h["name"]} for i, h in enumerate(items[:100])]}]
    return page(ROOT, path, title, desc, body, crumbs, ld, og_type="website", updated=updated)

def calendar_page(all_h, updated):
    ev = {}
    for h in all_h:
        for kind, key in (("특별공급", "sp_b"), ("청약 접수", "r_b"), ("당첨 발표", "win"), ("계약 시작", "c_b")):
            x = d(h[key])
            if x and (TODAY - dt.timedelta(days=3)) <= x <= (TODAY + dt.timedelta(days=45)):
                if kind == "청약 접수" and h["sp_b"] == h["r_b"]: continue
                ev.setdefault(x, []).append((kind, h))
    days = sorted(ev)
    blocks = []
    for x in days:
        lis = "".join(f'<li><span class="ek ek-{k.split()[0]}">{k}</span><a href="/danji/{h["id"]}/">{esc(h["name"])}</a><small>{esc(h["sido"])} · {esc(cat_label(h))}</small></li>'
                      for k, h in sorted(ev[x], key=lambda e: ("특별공급", "청약 접수", "당첨 발표", "계약 시작").index(e[0])))
        tag = "오늘" if x == TODAY else ("내일" if x == TODAY + dt.timedelta(days=1) else "")
        blocks.append(f'<section class="cday{" today" if x == TODAY else ""}{" past" if x < TODAY else ""}" id="d{x.isoformat()}"><h3>{x.month}월 {x.day}일 ({"월화수목금토일"[x.weekday()]}){(" <em>" + tag + "</em>") if tag else ""}</h3><ul>{lis}</ul></section>')
    body = (f'<header class="ph"><p class="cat">CALENDAR</p><h1>청약캘린더</h1><p class="lead">오늘부터 45일간의 특별공급·청약 접수·당첨 발표·계약 일정을 날짜별로 모았습니다. 단지명을 누르면 상세 정보를 볼 수 있습니다.</p></header>'
            '<p class="legend"><span class="ek ek-특별공급">특별공급</span><span class="ek ek-청약">청약 접수</span><span class="ek ek-당첨">당첨 발표</span><span class="ek ek-계약">계약 시작</span></p>'
            + "".join(blocks) + f'<p class="muted">데이터 기준일 {updated} · 출처 한국부동산원 청약홈</p>')
    return page(ROOT, "/calendar/", "청약캘린더 · 이번 주 청약 일정", "오늘의 청약 접수, 특별공급, 당첨자 발표, 계약 일정을 한눈에. 전국 아파트·오피스텔·무순위 청약 일정을 매일 업데이트합니다.",
                body, [("청약캘린더", "/calendar/")], [{"@context": "https://schema.org", "@type": "CollectionPage", "name": "청약캘린더", "url": SITE + "/calendar/"}], og_type="website", updated=updated)

# ───────────────────────── 메인 자동 영역 ─────────────────────────
def mini_card(h):
    return (f'<li><a href="/danji/{h["id"]}/">{badge(h)}<b>{esc(h["name"])}</b><small>{esc(h["sido"])} · {esc(cat_label(h))} · {h["units"]:,}세대</small>'
            f'<span>접수 {kdate(h["sp_b"] or h["r_b"])} · 발표 {kdate(h["win"])}</span>' + (f'<em>{esc(price_range(h))}</em>' if price_range(h) else "") + '</a></li>')

def ev_li(k, h):
    return f'<li><span class="ek ek-{k.split()[0]}">{k}</span><a href="/danji/{h["id"]}/">{esc(h["name"])}</a><small>{esc(h["sido"])}</small></li>'

def today_html(all_h, kinds, empty_word):
    ev = {}
    for h in all_h:
        for kind, key in kinds:
            x = d(h[key])
            if x and x >= TODAY and not (kind == "청약 접수" and h["sp_b"] == h["r_b"]): ev.setdefault(x, []).append((kind, h))
    if not ev: return f'<li class="empty">예정된 {empty_word} 일정이 없습니다.</li>'
    x = min(ev)
    head = "" if x == TODAY else f'<li class="nx">오늘은 {empty_word} 일정이 없어요 · 다음 일정 <b>{x.month}.{x.day}({"월화수목금토일"[x.weekday()]})</b></li>'
    return head + "".join(ev_li(k, h) for k, h in ev[x][:9])

def inject_home(all_h, updated):
    p = os.path.join(ROOT, "index.html")
    s = open(p, encoding="utf-8").read()
    today_ev = []
    for h in all_h:
        for kind, key in (("특별공급", "sp_b"), ("청약 접수", "r_b"), ("당첨 발표", "win")):
            if d(h[key]) == TODAY and not (kind == "청약 접수" and h["sp_b"] == h["r_b"]): today_ev.append((kind, h))
    week = sorted([h for h in all_h if d(h["sp_b"] or h["r_b"]) and TODAY < d(h["sp_b"] or h["r_b"]) <= TODAY + dt.timedelta(days=7)], key=lambda h: h["sp_b"] or h["r_b"])
    latest = sorted([h for h in all_h if h["cat"] != "R"], key=lambda h: h["notice"], reverse=True)[:8]
    remain = sorted([h for h in all_h if h["cat"] == "R" and status(h)[0] in ("예정", "접수중")], key=lambda h: h["r_b"])[:6]
    counts = {}
    for h in all_h:
        if status(h)[0] != "마감": counts[h["sido"]] = counts.get(h["sido"], 0) + 1
    blocks = {
        "today": today_html(all_h, (("특별공급", "sp_b"), ("청약 접수", "r_b")), "청약"),
        "todaywin": today_html(all_h, (("당첨 발표", "win"),), "당첨 발표"),
        "week": ("".join(f'<li><span class="dd">{kdate(h["sp_b"] or h["r_b"])}</span><a href="/danji/{h["id"]}/">{esc(h["name"])}</a><small>{esc(h["sido"])} · {esc(cat_label(h))}</small></li>' for h in week[:10])
                 or '<li class="empty">이번 주 접수 예정 단지가 없습니다.</li>'),
        "latest": "".join(mini_card(h) for h in latest),
        "remain": "".join(mini_card(h) for h in remain) or '<li class="empty">현재 접수 예정인 무순위·잔여세대가 없습니다.</li>',
        "regions": "".join((f'<a href="/bunyang/{slug}/"><b>{nm}</b><span>{counts.get(nm, 0)}</span></a>' if os.path.exists(os.path.join(ROOT, "bunyang", slug))
                            else f'<a class="zero" href="/bunyang/"><b>{nm}</b><span>0</span></a>') for nm, slug in SIDO),
        "updated": updated,
    }
    for k, v in blocks.items():
        s = re.sub(r"(<!--AUTO:%s-->).*?(<!--/AUTO:%s-->)" % (k, k), lambda m: m.group(1) + v + m.group(2), s, flags=re.S)
    open(p, "w", encoding="utf-8").write(s)
    json.dump({"updated": updated, "today": len(today_ev), "week": len(week), "total": len(all_h)},
              open(os.path.join(ROOT, "data", "home.json"), "w", encoding="utf-8"), ensure_ascii=False)

def export_json(all_h, updated):
    rows = []
    for h in all_h:
        ps = [t["price"] for t in h["types"] if t["price"]]
        rows.append({"id": h["id"], "n": h["name"], "s": h["sido"], "c": h["cat"], "cl": cat_label(h), "st": status(h)[0], "stt": status(h)[1],
                     "a": short_addr(h["addr"]), "u": h["units"], "rb": h["sp_b"] or h["r_b"], "w": h["win"],
                     "pn": min(ps) if ps else 0, "px": max(ps) if ps else 0, "ex": sorted({int(t["excl"]) for t in h["types"] if t["excl"]}),
                     "sp": sp_total(h), "pp": ppy_of(h)})
    json.dump({"updated": updated, "items": rows}, open(os.path.join(ROOT, "data", "danji.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

# ───────────────────────── 사이트맵 ─────────────────────────
def write_sitemap(gen_paths):
    static = [l.strip() for l in open(os.path.join(ROOT, "data", "static-urls.txt"), encoding="utf-8") if l.strip()]
    today = TODAY.isoformat()
    urls = []
    for line in static:
        p, pr, cf = (line.split("|") + ["0.5", "monthly"])[:3]
        urls.append((p, pr, cf))
    urls += [(p, pr, cf) for p, pr, cf in gen_paths]
    seen, x = set(), ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for p, pr, cf in urls:
        if p in seen: continue
        seen.add(p)
        x.append(f"  <url><loc>{SITE}{p}</loc><lastmod>{today}</lastmod><changefreq>{cf}</changefreq><priority>{pr}</priority></url>")
    x.append("</urlset>")
    open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8").write("\n".join(x) + "\n")
    return len(seen)

# ───────────────────────── 실행 ─────────────────────────
def main():
    if "--sample" in sys.argv:
        all_h = load_sample(sys.argv[sys.argv.index("--sample") + 1])
    else:
        all_h = load_live()
    # 중복 제거 + 최신순
    uniq = {}
    for h in all_h:
        if h["id"] and h["name"]: uniq[h["cat"] + h["id"]] = h
    if len(uniq) < 5:
        sys.exit("데이터가 너무 적습니다(API 오류 가능). 기존 페이지를 유지하고 종료합니다.")
    all_h = sorted(uniq.values(), key=lambda h: (h["notice"], h["id"]), reverse=True)
    updated = TODAY.isoformat()
    for nm, _ in SIDO:
        v = [ppy_of(h) for h in all_h if h["sido"] == nm and h["cat"] == "A" and ppy_of(h)]
        if v: REGION_PPY[nm] = (int(sum(v) / len(v)), len(v))
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    for sub in ("danji", "bunyang", "remain", "calendar"):
        shutil.rmtree(os.path.join(ROOT, sub), ignore_errors=True)
    gen = []
    for h in all_h:
        gen.append((danji_page(h, all_h, updated), "0.6", "weekly"))
    active = [h for h in all_h if status(h)[0] != "마감"] + [h for h in all_h if status(h)[0] == "마감"]
    gen.append((list_page("/bunyang/", "전국 분양정보", "전국 아파트·오피스텔·무순위·민간임대 분양 단지를 지역·유형·청약 상태별로 찾아보세요. 매일 업데이트됩니다.",
                          "전국 아파트·오피스텔·무순위·민간임대 분양 단지를 지역·유형·청약 상태별로 모았습니다. 매일 청약홈 공공데이터로 업데이트됩니다.",
                          active, [("분양정보", "/bunyang/")], updated), "0.9", "daily"))
    for nm, slug in SIDO:
        items = [h for h in active if h["sido"] == nm]
        if not items: continue
        gen.append((list_page(f"/bunyang/{slug}/", f"{nm} 분양정보", f"{nm} 지역 아파트·오피스텔 분양 단지와 청약 일정 {len(items)}곳. 분양가, 접수일, 당첨 발표일을 한눈에 확인하세요.",
                              f"{nm} 지역의 분양·청약 단지 {len(items)}곳입니다. 청약 일정과 분양가를 확인하고, 관심 단지는 상담을 신청해 보세요.",
                              items, [("분양정보", "/bunyang/"), (nm, f"/bunyang/{slug}/")], updated), "0.8", "daily"))
    rem = [h for h in active if h["cat"] == "R"]
    gen.append((list_page("/remain/", "무순위·잔여세대 청약", "무순위 청약, 잔여세대, 계약취소주택 재공급 정보를 모았습니다. 청약통장 없이 신청 가능한 줍줍 물량을 확인하세요.",
                          "무순위·잔여세대·계약취소주택 재공급 단지입니다. 일반적으로 청약통장 없이 신청할 수 있지만, 단지별 자격 요건은 공고문에서 꼭 확인하세요.",
                          rem, [("무순위·잔여세대", "/remain/")], updated), "0.8", "daily"))
    gen.append((calendar_page(all_h, updated), "0.9", "daily"))
    inject_home(all_h, updated)
    export_json(all_h, updated)
    n = write_sitemap(gen)
    print(f"done: {len(all_h)} danji, sitemap {n} urls")

if __name__ == "__main__":
    main()
