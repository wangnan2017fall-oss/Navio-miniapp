# LAVIO 健康管理 · 交互 Demo

奶油米白、墨绿版手机交互演示，包含 58 个页面入口、9 款示例商品及购物车、优惠券、订单、物流、售后等演示流程。

计划发布地址：`https://wangnan2017fall-oss.github.io/Navio-miniapp/`。以 Pages 工作流成功后的实际地址为准。

## 发布

1. 仓库 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。
2. 打开 **Actions → Publish LAVIO Demo to GitHub Pages**。首次提交会触发；也可点 **Run workflow**。
3. 发布成功后，从工作流的 `github-pages` 环境链接打开。

首次运行将按 SHA-256 清单同步已公开的确认稿，适配 GitHub 子目录，并把完整 `site/` 留存在本仓库。后续发布直接使用仓库中的文件，浏览时不依赖原托管平台。

手机框固定展示，内容在手机内滚动；左侧目录可切换页面。默认体验账户，演示验证码 `1234`。这是纯前端 Demo：数据保存在当前浏览器，不发送真实短信、不产生真实扣款或配送。原项目中的扩展入口不代表首期启用。

原全栈工程与许可证仍保留于仓库原目录；本目录只负责演示网页。
