# 微博博主正文原图下载器

一个 Python 3.11+ 交互式命令行程序，用于按日期区间下载微博博主原创正文中的图片。程序使用微博登录 Cookie 访问网页版时间线接口，支持 JPG、PNG、WebP 和 GIF。

## 功能

- 支持主页 URL 或纯数字 UID，包含 `https://weibo.com/u/<uid>`、`weibo.com/<uid>` 和移动端主页链接。
- 只处理原创微博正文，跳过转发微博、头像、背景图、视频和视频封面。
- 优先选择原图地址，原图不可用时保存最大可用版本并写入警告记录。
- 对图片和日期边界按北京时间处理，日期范围包含开始日和结束日。
- 文件名为 `YYYY-MM-DD_001.ext`，同一天已有文件时自动接续。
- 支持 Netscape `cookies.txt` 和浏览器开发者工具复制的 `Cookie:` 文本。
- 使用 `.part` 临时文件、状态文件和失败清单，支持安全重试与断点续传。
- 不按图片 URL 做内容去重：同一张图片由不同微博发布时会分别保存。

## 安装

```powershell
python -m pip install -r requirements.txt
```

开发和测试环境可安装：

```powershell
python -m pip install -r requirements-dev.txt
```

## 获取 Cookie

推荐使用浏览器扩展导出 Netscape 格式的 `cookies.txt`。也可以从已登录微博的浏览器开发者工具中复制请求头里的 `Cookie:` 值，保存为本地文本文件。

Cookie 文件属于敏感凭据，不要提交到 Git、上传到网盘或发送给他人。程序只读取该文件，不保存账号密码，也不会把 Cookie 内容写入日志。

## 使用

```powershell
python main.py
```

按提示依次输入：

```text
博主主页 URL 或 UID: https://weibo.com/u/1234567890
开始日期 (YYYY-MM-DD): 2026-01-01
结束日期 (YYYY-MM-DD): 2026-01-31
Cookie 文件路径: C:\path\to\cookies.txt
下载目录 [downloads]:
```

图片默认保存到 `downloads/` 下的平铺目录中。`.weibo_photo_state.json` 记录已成功下载的微博图片及降级来源，`.weibo_photo_failed.jsonl` 记录最终失败的图片。

## 原图与降级规则

程序按以下顺序尝试图片地址：

1. `original.url`
2. `largest.url`
3. `large.url`
4. 将 `thumbnail`、`bmiddle`、`mw690`、`orj360` 等已知缩略图路径转换为 `/large/`

只要使用的不是 `original` 地址，状态记录中的 `fallback` 就会标记为 `true`，任务结束时也会显示降级数量。图片不会经过重新编码，保存的是服务器返回的原始字节。

## 测试

```powershell
python -m pytest
```

自动测试使用模拟响应，不访问微博。真实抓取会受微博登录状态、限流和页面接口变化影响，建议先用一个较短的日期区间验证。

## 说明

本项目依赖微博网页版当前非公开接口，微博改版后解析逻辑可能需要更新。请确保自己拥有访问和下载相关内容的合法权限，并遵守微博服务条款、版权要求和适用法律；不要用于绕过访问限制或高频抓取。
