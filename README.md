# 食客通 · Social Review Monitor

自动监控全网提及食客通 / Tarro 的评论与内容，每日更新，部署在 GitHub Pages。

## 自动抓取来源

| 来源 | 方式 | 需要设置 |
|------|------|---------|
| **Google Search** | Custom Search API | `GOOGLE_API_KEY` + `GOOGLE_CSE_ID` |
| **Reddit** | 公开 JSON API（免费，无需 key） | 无 |
| **Yelp** | HTML 爬取（无需 API key） | 可选填 `YELP_URLS` 指定页面 |
| **Google Maps 评论** | Places API | `GOOGLE_API_KEY` + `GOOGLE_PLACE_IDS` |

> **小红书 / 微信 / Facebook** 有登录墙，只能手动录入。点页面右上角「+ 手动录入」，AI 自动分析情感。

---

## 部署步骤（5 分钟）

### 1. 创建 GitHub repo，上传文件

保持以下目录结构：
```
├── index.html
├── data/
│   ├── reviews.json
│   └── meta.json
├── scripts/
│   └── scrape.py
└── .github/workflows/
    └── scrape.yml
```

### 2. 开启 GitHub Pages

Settings → Pages → Source: **Deploy from branch** → `main` / `(root)`

访问：`https://<用户名>.github.io/<repo名>/`

### 3. 配置 Secrets（让自动抓取生效）

Settings → Secrets and variables → Actions → New repository secret

| Secret | 说明 | 必填 |
|--------|------|------|
| `GOOGLE_API_KEY` | Google Cloud API key（开启 Custom Search + Places API） | 推荐 |
| `GOOGLE_CSE_ID` | 在 [cse.google.com](https://cse.google.com) 创建，搜索范围选「全网」 | 推荐 |
| `GOOGLE_PLACE_IDS` | 逗号分隔，如 `ChIJabc123,ChIJdef456` | 可选 |
| `YELP_URLS` | 逗号分隔 Yelp 业务页面 URL | 可选 |

> **不填任何 Secret 也能用** — Reddit 抓取完全免费无需 key，会自动跑。

### 4. 手动触发

Repo → Actions → Daily Review Scrape → **Run workflow**

---

## 如何获取 Google CSE ID

1. 访问 [cse.google.com](https://cse.google.com)
2. 新建搜索引擎 → 搜索范围选「搜索整个网络」
3. 搜索关键词填：`食客通 OR Tarro restaurant`
4. 创建后复制搜索引擎 ID（格式如 `a1b2c3d4e5f6g:xyz`）

---

## 数据格式 `data/reviews.json`

```json
{
  "id": "abcd1234",
  "platform": "Reddit",
  "source_name": "r/ChineseFood",
  "author": "username",
  "date": "2025-04-08",
  "rating": null,
  "text": "评论原文",
  "url": "https://...",
  "mentions_tarro": true,
  "sentiment": "positive",
  "category": "好评",
  "manual": false,
  "fetched_at": "2025-04-08T14:00:00Z"
}
```
