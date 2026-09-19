# B站视频数据分析 · Streamlit 应用

实时调用 B站公开 API（WBI 签名）抓取视频信息与评论，做多维分析的可视化 Web 应用。

## 功能
- **选视频**：关键词搜索 B站视频并下拉选择，或直接粘贴 BV 号 / 视频链接
- **真实数据**：播放、点赞、投币、收藏、弹幕、评论数等 KPI
- **评论挖掘**：发布时段分布、字数/点赞分布、高频词、词云、情感倾向、高赞 Top10
- **云端中文**：内置 Noto Sans SC 字体，Streamlit Cloud 上中文正常渲染

## 本地运行
```bash
pip install -r requirements.txt
streamlit run app.py
```

## 部署到 Streamlit Cloud
1. 把本仓库推到你的 GitHub（公开仓库）
2. 打开 https://share.streamlit.io （或 streamlit.io/cloud）
3. 点击 **New app** → 选择本仓库 → 分支 `main` → 入口文件 `app.py`
4. 点击 **Deploy**，等待构建完成即可获得公网访问地址

## 接口说明
- 视频信息：`x/web-interface/view`（无需签名）
- 评论：`x/v2/reply/wbi/main`（需 WBI 签名 + 游标分页）
- 搜索：`x/web-interface/wbi/search/all/v2`（需 WBI 签名）

> 仅供学习演示，请遵守 B站相关使用规范，控制请求频率。
