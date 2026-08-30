# 部署

> ✅ **已部署**：`https://mock.windgraham.art`（Nginx 反代 :3101 到生产 Next.js；agent API :8000；Let's Encrypt 证书已签发并自动续期）。
> ⚠️ 注意：本机自身的 DNS resolver 对刚添加的 `mock.windgraham.art` 有**过期负缓存**（有时本地解析失败），**不影响外部访问**（1.1.1.1/8.8.8.8 均解析到 115.190.185.53）。如需本机直接访问可 `curl --resolve mock.windgraham.art:443:115.190.185.53 https://mock.windgraham.art/`。

## 1. SSH 访问（需要往服务器加 2 个 SSH 公钥）
- 本机已生成一对：`deploy/aiic_ed25519.pub`（公钥，可提交）。**私钥 `deploy/aiic_ed25519` 已 gitignore，绝不上传。**
- 把**本机公钥** + **你自己的另一把公钥**（或协作机器公钥）加入服务器：
  ```bash
  cat deploy/aiic_ed25519.pub >> ~/.ssh/authorized_keys   # 在服务器上
  # 或本地： ssh-copy-id -i deploy/aiic_ed25519.pub user@server
  ```
- 连接：`ssh -i deploy/aiic_ed25519 user@server`

## 2. 拷贝代码 + 配环境
```bash
# 把仓库推到 GitHub 后，服务器上：
git clone <repo-url> /root/AIIC-Project
cd /root/AIIC-Project/apps/agent && cp .env.example .env && vim .env   # 填 DEEPSEEK/GEMINI/VOLCENGINE/MINIMAX 等 key
```

## 3. 一键构建/启动
```bash
bash /root/AIIC-Project/scripts/deploy.sh
```

## 4. 系统服务（常驻，可选）
```bash
sudo cp /root/AIIC-Project/deploy/aiic-agent.service /root/AIIC-Project/deploy/aiic-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aiic-agent aiic-web
```

## 5. 反代 + HTTPS（公开 URL）
```bash
sudo cp /root/AIIC-Project/deploy/nginx.conf /etc/nginx/sites-available/probe
sudo ln -s /etc/nginx/sites-available/probe /etc/nginx/sites-enabled/probe
# 改 nginx.conf 里的 server_name 为你的域名
sudo nginx -t && sudo nginx -s reload
sudo certbot --nginx -d your.domain   # 自动 HTTPS
```

## 6. 验证
- `http://your.domain` 打开首页 → 预约 → 面试房间 → 报告 → 分享。
- `curl https://your.domain/api/interviews/prepare` 可跑通即部署成功。
