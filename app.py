# -*- coding: utf-8 -*-
"""
B站视频数据分析 · Streamlit 应用
- 支持「搜索关键词选视频」或「直接输入 BV 号/链接」
- 实时调用 B站公开 API（WBI 签名）获取视频信息与多页评论
- 多维分析：KPI、发布时段、字数/点赞分布、关键词词频、词云、情感倾向、高赞 Top
- 自包含：内置 Noto Sans SC 字体，云端中文正常渲染
"""
import re
import time
import hashlib
import datetime as dt
from pathlib import Path
from collections import Counter

import requests
import numpy as np
import streamlit as st
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import jieba
from wordcloud import WordCloud

# ---------------- 中文字体 ----------------
FONT_PATH = None
for _c in [Path(__file__).parent / "fonts" / "NotoSansSC-Regular.otf",
           Path(r"C:\Windows\Fonts\msyh.ttc"),
           Path(r"C:\Windows\Fonts\simhei.ttf")]:
    if _c.exists():
        FONT_PATH = str(_c)
        break
if FONT_PATH:
    font_manager.fontManager.addfont(FONT_PATH)
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=FONT_PATH).get_name()
plt.rcParams["axes.unicode_minus"] = False

# ---------------- 请求 & WBI 签名 ----------------
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://www.bilibili.com",
})
_MIXIN_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
              27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
              37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 57, 56, 11, 36,
              20, 34, 44, 22, 54, 21, 60, 51, 59, 6, 30, 4, 25, 52, 62, 63, -1]
_WBI_KEYS = None

def _get_wbi_keys():
    global _WBI_KEYS
    if _WBI_KEYS is None:
        nav = SESSION.get("https://api.bilibili.com/x/web-interface/nav", timeout=15).json()
        img = nav["data"]["wbi_img"]["img_url"].split("/")[-1].split(".")[0]
        sub = nav["data"]["wbi_img"]["sub_url"].split("/")[-1].split(".")[0]
        _WBI_KEYS = (img, sub)
    return _WBI_KEYS

def wbi_sign(params):
    img_key, sub_key = _get_wbi_keys()
    mixin = "".join((img_key + sub_key)[i] for i in _MIXIN_TAB[:32])
    p = dict(params)
    p["wts"] = round(time.time())
    p = dict(sorted(p.items()))
    p = {k: "".join(c for c in str(v) if c not in "!'()*") for k, v in p.items()}
    q = "&".join(f"{k}={v}" for k, v in p.items())
    p["w_rid"] = hashlib.md5((q + mixin).encode()).hexdigest()
    return p

def _get_json(url, params=None):
    for _ in range(3):
        try:
            r = SESSION.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception:
            time.sleep(1)
    return {}

# ---------------- 数据抓取 ----------------
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_video(bvid):
    d = _get_json("https://api.bilibili.com/x/web-interface/view", {"bvid": bvid})
    if d.get("code") != 0 or not d.get("data"):
        return None
    v = d["data"]
    return {
        "bvid": v["bvid"], "aid": v["aid"], "title": v["title"],
        "owner": v["owner"]["name"], "view": v["stat"]["view"],
        "danmaku": v["stat"]["danmaku"], "reply": v["stat"]["reply"],
        "like": v["stat"]["like"], "coin": v["stat"]["coin"],
        "favorite": v["stat"]["favorite"], "share": v["stat"]["share"],
        "duration": v["duration"], "pubdate": v["pubdate"],
        "desc": v.get("desc", ""), "tname": v.get("tname", ""),
    }

@st.cache_data(ttl=1800, show_spinner=False)
def search_videos(keyword, limit=10):
    params = wbi_sign({"keyword": keyword, "page": 1})
    d = _get_json("https://api.bilibili.com/x/web-interface/wbi/search/all/v2", params)
    out = []
    for grp in (d.get("data", {}).get("result") or []):
        if grp.get("result_type") == "video":
            for it in grp.get("data", [])[:limit]:
                out.append({
                    "bvid": it.get("bvid"),
                    "title": re.sub(r"<.*?>", "", it.get("title", "")),
                    "author": it.get("author", ""),
                    "play": int(it.get("play", 0) or 0),
                })
            break
    return out

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_comments(aid, pages=20, mode=3):
    comments = []
    nxt = 0
    for _ in range(pages):
        params = wbi_sign({"type": 1, "oid": aid, "mode": mode, "next": nxt})
        d = _get_json("https://api.bilibili.com/x/v2/reply/wbi/main", params)
        if d.get("code") != 0:
            break
        data = d.get("data") or {}
        replies = data.get("replies") or []
        if not replies:
            break
        for it in replies:
            msg = it["content"]["message"]
            if msg.strip() in ("", "[视频]"):
                continue
            comments.append({
                "uname": it["member"]["uname"], "message": msg,
                "ctime": it["ctime"], "like": it["like"],
                "rpid": it["rpid"], "sex": it["member"].get("sex", ""),
            })
        cursor = data.get("cursor") or {}
        if cursor.get("is_end"):
            break
        nxt = cursor.get("next", 0)
        if not nxt:
            break
        time.sleep(0.2)
    return comments

# ---------------- 中文处理 ----------------
STOPWORDS = set("""
的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这 那 与他 她 它 们
什么 怎么 怎样 如何 为什么 因为 所以 但是 如果 虽然 而且 并且 然后 啊 吧 呢 吗 哦 嗯 呀 啦 嘛 咯 额 哎 哈 哇
就是 这个 那个 一些 一样 可以 已经 还是 不是 这样 那样 这些 那些 这种 那种 这里 那里 哪个 多少 几个 一下 一直
现在 刚才 后来 之前 之后 时候 今天 明天 昨天 年 月 日 号 点 分 秒 我们 你们 他们 大家 别人 谁 哪儿 多 少 还 又 再
太 最 更 比较 十分 非常 特别 有点 稍微 全 只 仅 仅仅 不 没 无 别 及 与 同 跟 给 向 对 从 由 被 把 让 使 为 以 于
而 则 却 且 若 如 虽 纵 既 即 之 其 此 该
""".split())

def cut_words(texts):
    words = []
    for t in texts:
        for w in jieba.lcut(t):
            w = w.strip()
            if len(w) < 2 or w in STOPWORDS or re.fullmatch(r"[\s\W\d]+", w):
                continue
            words.append(w)
    return words

POS = set("赞 好 喜欢 爱 牛 厉害 强 优秀 棒 顶 支持 感谢 感动 泪目 可爱 舒服 神 绝 香 冲 牛逼 牛批 可以 完美 精彩 好看 真实 有趣 笑死 哈哈 推荐 满分 妙 美 棒棒".split())
NEG = set("差 烂 无聊 水 坑 骗 假 黑 喷 骂 垃圾 失望 难看 恶心 劝退 退坑 崩 槽 吐槽 雷 尬 烂尾 敷衍 抄袭 糊 拉胯 翻车 塌房 摆烂 菜 弱 坏 烦 气 怒 悲 惨".split())

def sentiment(text):
    score = 0
    for w in jieba.lcut(text):
        if w in POS:
            score += 1
        elif w in NEG:
            score -= 1
    return "正面" if score > 0 else ("负面" if score < 0 else "中性")

# ---------------- 图表 ----------------
def chart_hour(comments):
    hours = [dt.datetime.fromtimestamp(c["ctime"], dt.timezone(dt.timedelta(hours=8))).hour for c in comments]
    cnt = Counter(hours); xs = list(range(24)); ys = [cnt.get(h, 0) for h in xs]
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.bar(xs, ys, color="#00aeec")
    ax.set_title("评论发布时段分布（北京时间）"); ax.set_xlabel("小时"); ax.set_ylabel("评论数")
    ax.set_xticks(xs)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    return fig

def chart_len(comments):
    lens = [len(c["message"]) for c in comments]
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.hist(lens, bins=[0, 5, 10, 20, 40, 60, 80, 100, 200, 400], color="#fb7299", edgecolor="white")
    ax.set_title("评论字数分布"); ax.set_xlabel("字数"); ax.set_ylabel("评论数")
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    return fig

def chart_like(comments):
    likes = [c["like"] for c in comments]
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.hist(np.array(likes) + 0.1, bins=[0, 1, 10, 50, 100, 500, 1000, 5000], color="#ff9a3c", edgecolor="white")
    ax.set_title("评论点赞数分布"); ax.set_xlabel("点赞数（对数区间）"); ax.set_ylabel("评论数"); ax.set_xscale("symlog")
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    return fig

def chart_word(words, top=20):
    common = Counter(words).most_common(top)
    labels = [w for w, _ in common][::-1]; vals = [n for _, n in common][::-1]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(labels, vals, color="#00aeec")
    ax.set_title(f"高频词 Top {top}")
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    return fig

def chart_sent(comments):
    cnt = Counter(sentiment(c["message"]) for c in comments)
    labels = ["正面", "中性", "负面"]; vals = [cnt.get(k, 0) for k in labels]
    fig, ax = plt.subplots(figsize=(4.5, 4.5))
    ax.pie(vals, labels=[f"{l}\n{v}" for l, v in zip(labels, vals)],
           colors=["#00aeec", "#cfd8dc", "#fb7299"], autopct="%1.1f%%", startangle=90)
    ax.set_title("评论情感倾向")
    return fig

def make_wordcloud(words):
    if not FONT_PATH or not words:
        return None
    try:
        wc = WordCloud(font_path=FONT_PATH, width=800, height=400, background_color="white",
                       max_words=120, colormap="viridis").generate(" ".join(words))
        return wc.to_image()
    except Exception:
        return None

# ---------------- UI ----------------
st.set_page_config(page_title="B站视频数据分析", page_icon="📊", layout="wide")
st.title("📊 B站视频数据分析 · 评论挖掘")
st.caption("实时调用 B站公开 API（WBI 签名）抓取真实数据 · 仅供学习演示")

col_mode = st.container()
with col_mode:
    tab1, tab2 = st.tabs(["🔍 搜索选视频", "🔗 直接输入 BV / 链接"])
    if "bvid" not in st.session_state:
        st.session_state["bvid"] = ""
    with tab1:
        kw = st.text_input("输入关键词，搜索 B站视频", placeholder="例如：原神 / 何同学 / 美食")
        if st.button("搜索", key="search"):
            if kw.strip():
                with st.spinner("搜索中…"):
                    res = search_videos(kw.strip())
                if res:
                    labels = [f"{r['title']}  ·  UP {r['author']}  ·  {r['play']:,} 播放" for r in res]
                    sel = st.selectbox("选择要分析视频", labels)
                    st.session_state["bvid"] = res[labels.index(sel)]["bvid"]
                    st.success(f"已选择：{st.session_state['bvid']}")
                else:
                    st.warning("未找到相关视频，换个关键词试试")
    with tab2:
        link = st.text_input("粘贴 BV 号或视频链接", placeholder="BV1GJ411x7h7 或 https://www.bilibili.com/video/BV1GJ411x7h7")
        if link:
            m = re.search(r"BV[0-9A-Za-z]+", link)
            if m:
                st.session_state["bvid"] = m.group(0)
                st.success(f"识别到：{st.session_state['bvid']}")
            else:
                st.error("未识别到 BV 号")

pages = st.slider("抓取评论页数（每页 20 条）", 1, 50, 20, help="页数越多，分析样本越大、耗时越长")
analyze = st.button("🚀 开始分析", type="primary", use_container_width=True)

if analyze:
    bvid = st.session_state.get("bvid", "")
    if not bvid:
        st.error("请先选择或输入一个视频（BV 号）")
        st.stop()
    with st.spinner("正在抓取视频信息与评论…"):
        video = fetch_video(bvid)
    if not video:
        st.error("视频信息获取失败，请检查 BV 号是否正确（该视频可能已下架或设为私密）")
        st.stop()
    with st.spinner("正在抓取评论…"):
        comments = fetch_comments(video["aid"], pages)
    if not comments:
        st.warning("未能抓取到评论")
        st.stop()

    eng = video["like"] + video["coin"] + video["favorite"] + video["reply"]
    eng_rate = eng / video["view"] * 100 if video["view"] else 0
    pub = dt.datetime.fromtimestamp(video["pubdate"]).strftime("%Y-%m-%d %H:%M")
    sent = Counter(sentiment(c["message"]) for c in comments)
    avg_like = np.mean([c["like"] for c in comments]) if comments else 0

    st.header(f"{video['title']}")
    st.caption(f"UP主：{video['owner']} ｜ 分区：{video['tname']} ｜ 发布：{pub} ｜ {video['bvid']}")

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("播放量", f"{video['view']:,}")
    k2.metric("点赞", f"{video['like']:,}")
    k3.metric("投币", f"{video['coin']:,}")
    k4.metric("收藏", f"{video['favorite']:,}")
    k5, k6, k7, k8 = st.columns(4)
    k5.metric("评论总数(站)", f"{video['reply']:,}")
    k6.metric("弹幕", f"{video['danmaku']:,}")
    k7.metric("分享", f"{video['share']:,}")
    k8.metric("互动率", f"{eng_rate:.1f}%")

    st.info(f"本次抓取评论 **{len(comments)}** 条 ｜ 平均点赞 **{avg_like:.1f}** ｜ "
            f"情感：正面 {sent.get('正面',0)} / 中性 {sent.get('中性',0)} / 负面 {sent.get('负面',0)}")

    texts = [c["message"] for c in comments]
    words = cut_words(texts)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("评论发布时段分布")
        st.pyplot(chart_hour(comments), use_container_width=True)
    with c2:
        st.subheader("评论字数分布")
        st.pyplot(chart_len(comments), use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        st.subheader("评论点赞数分布")
        st.pyplot(chart_like(comments), use_container_width=True)
    with c4:
        st.subheader("评论情感倾向")
        st.pyplot(chart_sent(comments), use_container_width=True)

    st.subheader("高频词 Top 20")
    st.pyplot(chart_word(words, 20), use_container_width=True)

    st.subheader("评论词云")
    cloud = make_wordcloud(words)
    if cloud:
        st.image(cloud, use_container_width=True)
    else:
        st.warning("未找到中文字体，跳过词云生成。")

    st.subheader("高赞评论 Top 10")
    top = sorted(comments, key=lambda c: c["like"], reverse=True)[:10]
    st.table([{"用户": c["uname"], "评论": c["message"], "点赞": f"{c['like']:,}"} for c in top])

    st.caption(f"生成时间 {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} · 数据来源 B站公开 API")
