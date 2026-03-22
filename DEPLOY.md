# OpenClaw 下载官网部署说明

## 站点目录

`/root/.openclaw/workspace/openclaw-download-site`

## 页面清单

- `/` — 官网首页
- `/downloads/` — 下载页
- `/guide/` — 安装指南
- `/security/` — 安全校验
- `/releases/` — 版本历史
- `/assets/styles.css` — 统一样式
- `/assets/site.js` — 交互脚本（复制、OS检测）
- `/assets/og-image.svg` — OG 分享图片
- `/robots.txt` — 搜索引擎爬虫规则
- `/sitemap.xml` — 站点地图
- `/downloads/stats.json` — 下载计数（每30分钟更新）
- `/downloads/manifest.json` — 版本清单

## 部署步骤

### 1. 申请子域名

在阿里云域名管理中添加 A 记录：
- 主机记录：`download`
- 记录值：`47.97.124.121`
- TTL：600

### 2. 创建 nginx 配置

```nginx
server {
    listen 80;
    server_name download.zhjjq.tech;

    root /root/.openclaw/workspace/openclaw-download-site;
    index index.html;

    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    location ~* \.(css|js|svg|png|jpg|jpeg|gif|ico|woff2?)$ {
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    location /downloads/ {
        autoindex off;
        types {
            application/octet-stream exe;
            application/json json;
        }
        location ~* \.exe$ {
            add_header Content-Disposition "attachment";
            add_header Cache-Control "no-cache";
        }
        try_files $uri $uri/ =404;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }

    gzip on;
    gzip_types text/html text/css application/json application/javascript text/xml;
    gzip_min_length 1024;

    location ~ /\. {
        deny all;
    }
}
```

### 3. 申请 SSL 证书

```bash
certbot --nginx -d download.zhjjq.tech
```

### 4. 重载 nginx

```bash
nginx -t
nginx -s reload
```

## 发版 SOP

每次发新版本：

1. 把新安装包放入 `downloads/` 目录
2. 文件名带版本号：`OpenClaw-Installer-Setup-X.Y.Z.exe`
3. 计算 SHA256：`sha256sum OpenClaw-Installer-Setup-X.Y.Z.exe`
4. 更新以下文件：
   - `downloads/manifest.json`
   - `downloads/index.html`
   - `security/index.html`
   - `releases/index.html`
   - `index.html`（首页版本号）
5. `nginx -s reload`

## 设计规范

- 深色科技风（#09090b 背景）
- Inter + JetBrains Mono 字体
- 蓝紫渐变主色调
- 全响应式（桌面/平板/手机）
- SVG 内联图标
- 参考：Python.org / Node.js / Docker 官网
