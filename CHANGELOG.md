# Changelog

## [1.0.0] - 2026-03-20
### Added
- 首个 Windows 图形安装器（NSIS 打包）
- 官方下载中心：下载页、安装指南、安全校验、版本历史
- manifest.json 版本清单
- SHA256 校验展示

## [Unreleased] - 2026-03-22
### Added
- Flask 后端 API（下载日志、统计、版本管理）
- SQLite 数据库持久化
- 下载数据面板 `/dashboard/`
- 版本管理后台 `/admin/`
- 一键发版脚本 `publish_release.py`
- 下载事件追踪与前端 Toast 提示
- 品牌资源升级：龙虾 logo、favicon、OG 图
- 增强统计维度：today / 30d / source / by_hour / unique_ips_30d / versions_total
- 来源归类统计（Direct / GitHub / Docs / Discord / Search / Self 等）
- 后台支持直接上传安装包
- 后台支持"上传后直接发布"一步完成
- 7 天趋势折线图（canvas 绘制）

### Changed
- 管理后台默认登录密码调整为 `admin`，便于景总直接登录
- Nginx 启用访问日志并增加 `/api/*` 反代
- 全站静态资源增加版本戳，修复缓存导致的页面异常
- HTML 页面增加 `Cache-Control: no-cache` 避免浏览器强缓存
- 下载统计改为从 API 实时获取
- 下载页与版本页改为读取真实版本数据
- 首页、下载页、版本页进行第二轮视觉升级
- Dashboard 来源统计改为归类展示

### Fixed
- 修复 `access_log off` 导致的统计失效
- 修复 favicon 缺失导致的 404
- 修复子页面可能受旧缓存影响无法正常打开的问题
- 修复 admin/index.html JS 代码污染问题
