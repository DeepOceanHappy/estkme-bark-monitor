# ESTKme Bark Stock Monitor

一个轻量的 ESTKme 商品补货监控工具。它会定时请求 ESTKme 商品接口，监控指定规格的库存和购买状态，并在补货时通过 Bark 推送到手机。

默认监控：

- 商品接口：`https://api.estk.me/user/shop/products/1`
- 商品页面：`https://store.estk.me/products/1`
- 规格：`ESTKme Max`
- 检测间隔：`60` 秒

## 功能

- 监控指定商品规格的库存、价格、状态、预售状态
- 库存从 `0` 变为大于 `0`，或商品从不可购买变为可购买时发送 Bark 推送
- 提供本地 Web 页面查看状态、修改配置、手动检测、测试 Bark
- 支持 Docker Compose 部署
- 支持 systemd 常驻部署
- 无第三方 Python 依赖，只需要 Python 3

## 安全提醒

不要把真实 Bark Key 提交到 GitHub。仓库里只应该保留 `.env.example`，真实配置请放在服务器上的 `.env`。

监控页面默认只绑定 `127.0.0.1`，不建议直接暴露到公网。如果需要查看页面，推荐使用 SSH 隧道。

请保持合理检测间隔，例如 `60` 秒或更长，避免对目标接口造成不必要压力。

## 快速部署：Docker Compose

把项目上传到服务器后：

```bash
cd estkme-bark-monitor
cp .env.example .env
nano .env
docker compose up -d --build
```

`.env` 里至少填写：

```bash
BARK_KEY=你的BarkKey
```

查看日志：

```bash
docker compose logs -f
```

停止并删除容器：

```bash
docker compose down
```

## 查看监控页面

Docker Compose 默认把页面绑定到服务器本机 `127.0.0.1:8765`。

在你的电脑执行：

```bash
ssh -L 8765:127.0.0.1:8765 root@你的服务器IP
```

然后在本机浏览器打开：

```text
http://127.0.0.1:8765/
```

## systemd 部署

如果不用 Docker，可以把项目放到 `/opt/estkme-bark-monitor`：

```bash
cd /opt/estkme-bark-monitor
cp .env.example .env
nano .env
sudo cp estkme-bark-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now estkme-bark-monitor
```

查看状态和日志：

```bash
sudo systemctl status estkme-bark-monitor
journalctl -u estkme-bark-monitor -f
```

如果服务器上的 Python 路径不是 `/usr/bin/python3`，请修改 `estkme-bark-monitor.service` 里的 `ExecStart`。

## Windows 本地运行

双击 `start.bat`，或在当前目录运行：

```powershell
.\start.bat
```

然后打开：

```text
http://127.0.0.1:8765/
```

本地运行时电脑关机后监控会停止，所以更推荐放在云服务器。

## 配置项

可以在 `.env` 中配置：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `BARK_KEY` | 空 | Bark Key，必填 |
| `BARK_SERVER` | `https://api.day.app` | Bark 服务地址，自建 Bark 可修改 |
| `BARK_SOUND` | `glass` | Bark 提示音 |
| `ESTKME_PRODUCT_API` | `https://api.estk.me/user/shop/products/1` | 商品接口 |
| `ESTKME_PRODUCT_PAGE` | `https://store.estk.me/products/1` | 商品页面 |
| `ESTKME_VARIANT_TITLE` | `ESTKme Max` | 要监控的规格名称 |
| `ESTKME_INTERVAL_SECONDS` | `60` | 检测间隔，最小 `15` 秒 |
| `ESTKME_NOTIFY_ON_STARTUP_IF_AVAILABLE` | `true` | 启动时如果已有库存是否推送 |
| `ESTKME_HOST` | `127.0.0.1` | Web 页面监听地址 |
| `ESTKME_PORT` | `8765` | Web 页面端口 |
| `ESTKME_DATA_DIR` | `./data` | 运行状态保存目录 |

## 项目结构

```text
.
├── .env.example
├── .gitignore
├── .dockerignore
├── Dockerfile
├── docker-compose.yml
├── estkme-bark-monitor.service
├── index.html
├── server.py
├── start.bat
└── README.md
```

运行后可能生成：

- `config.json`
- `state.json`
- `data/`

这些文件可能包含 Bark Key 或运行状态，已在 `.gitignore` 中排除。

## Bark 推送内容

补货时会推送类似内容：

```text
ESTKme 上架提醒
商品系列：ESTKme P-series
规格：ESTKme Max
价格：200.00
库存：1
状态：1
预售：否
提醒原因：库存从 0 变为 1
```

## 发布到 GitHub

确认 `.env`、`config.json`、`state.json`、`data/` 没有被提交后：

```bash
git init
git add .
git commit -m "Add ESTKme Bark stock monitor"
git branch -M main
git remote add origin https://github.com/你的用户名/estkme-bark-monitor.git
git push -u origin main
```

## 免责声明

本项目仅用于个人补货提醒。请合理设置检测间隔，并遵守目标网站的使用规则。
