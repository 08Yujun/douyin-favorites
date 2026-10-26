# 抖音收藏盒（douyin-favorites）

同步抖音「收藏」内容到本地，按主题（如「AI学习」「高数」）自动分类，
并提供卡片流浏览界面（含 AI 要点摘要）。数据全部存在本机 SQLite，不上传。

## 功能

- **sync**：Playwright 半自动抓取收藏列表（首次扫码登录，之后免登录）
- **classify**：关键词规则前置 + LLM 多标签分类（兼容 DeepSeek / 通义 / OpenAI 等），
  同时生成一句话 AI 摘要；你在界面上的手动纠正会沉淀为示例，越用越准
- **web**：本地卡片流界面——类型切换、类目筛选、全文搜索、手动改分类

## 快速开始

```powershell
cd douyin-favorites
python -m pip install -r requirements.txt

# 若要做真实同步，另需安装浏览器内核（下载约 130MB）
# 国内网络可加速：
#   $env:PLAYWRIGHT_DOWNLOAD_HOST="https://cdn.npmmirror.com/binaries/playwright"
python -m playwright install chromium

copy config.example.toml config.toml   # 然后编辑：填 LLM key、改类目关键词

python main.py demo      # 写入演示数据，先看看界面效果
python main.py web       # 打开 http://127.0.0.1:8642
```

## 真实同步流程

```powershell
python main.py sync
```

1. 弹出浏览器窗口，登录抖音（首次登录状态会保存到 `data/browser_profile`）；
2. 在浏览器里点开自己的「收藏」页面；
3. 回到终端按 Enter —— 脚本重载页面并自动滚动，实时收集接口数据；
4. 结束后运行 `python main.py classify` 完成分类，再 `python main.py web` 浏览。

> 抖音没有官方开放 API，本工具仅抓取**自己账号**的收藏做个人备份，
> 请控制频率（默认每屏 1.5 秒），勿用于公开传播。抖音网页接口可能变动，
> 若抓不到数据请查看 `data/better_favorites.db` 是否有新增，或调小 scroll_wait 重试。

## 数据结构

- 数据库：`data/better_favorites.db`
  - `items`：收藏条目（标题/作者/标签/封面/摘要/分类/置信度……）
  - `corrections`：你的手动分类记录，作为 LLM few-shot 示例
- 配置：`config.toml`（LLM 接口、同步参数、类目定义）

## 目录

```
main.py               命令行入口
config.toml           本机配置（LLM 接口、类目、同步参数）
dyfav/
  config.py           配置加载
  db.py               SQLite 存储层
  sync.py             Playwright 同步器（增量模式：无新内容快速停止）
  classify.py         规则 + LLM 批量分类
  auto.py             定时自动同步循环
  server.py           FastAPI 接口
  static/index.html   卡片流界面
launch.ps1            桌面快捷方式用的启动脚本
```

## 自动化（可选，已配置）

- `python main.py auto`：常驻循环，按 `[auto].interval_minutes` 定时后台同步 + 增量分类
- 开机自启快捷方式位于：`shell:startup`（运行中日志见 `data/auto.log`）
- 无头模式运行（`[sync].headless = true`），不会弹窗口；登录态保存在 `data/browser_profile`

