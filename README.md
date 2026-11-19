# Navio-miniapp

基于芋道开源栈搭建的营养品私域商城开发项目，包含微信小程序、Java 后端、管理后台和商城静态资源。

目标是先跑通 **商品展示 → 详情与规格 → 下单与优惠券 → 支付与物流** 的基础流程，再逐步完成前端视觉改版和供应商对接。

## 当前进度

- 已整合四个项目，启用后端会员、支付、商品、营销、交易和统计模块。
- 原本机环境已完成后端构建与启动，7 项模板、商品和价格接口检查通过。
- 已准备本地演示数据库、3 款测试商品，以及启动、停止和验证脚本。
- 新版 UI 尚未替换；真实微信登录、下单支付、供应商货盘及物流履约仍待配置和联调。
- 拼团、众筹等高级营销暂不纳入本轮 MVP。

目前是**可继续开发的本地演示基线**，尚未作为线上商城交付。

## 目录说明

| 目录 | 用途 |
|---|---|
| `ruoyi-vue-pro/` | Java 后端：商品、会员、订单、营销、支付等 API |
| `yudao-mall-uniapp/` | uni-app / Vue 3 小程序前端 |
| `yudao-ui-admin-vue3/` | Vue 3 管理后台 |
| `yudao-demo/` | 此前下载的商城静态资源 |

四个目录保存真实文件，不使用 Git 子模块。`yudao-demo` 仅包含已下载的 `yudao-static/mall/` 及根元数据。

## 本地运行

下面各组命令分别从仓库根目录执行；前端和管理后台请另开终端运行。

### 1. 准备环境与源码

后端使用 **JDK 17、Maven 3.9.x、MySQL 8.4、Redis 7.4、Python 3.9+**；小程序使用 **Node.js、HBuilderX 和微信开发者工具**。管理后台要求 Node.js ≥ 20.19、pnpm ≥ 10.28。

~~~bash
git clone https://github.com/wangnan2017fall-oss/Navio-miniapp.git
cd Navio-miniapp
~~~

不要求安装 Docker。当前本地管理脚本按 macOS 编写，需要将运行包放在仓库根目录的 `.local-runtime/`：

~~~text
.local-runtime/
├── amazon-corretto-17.jdk/Contents/Home/bin/java
├── apache-maven-3.9.9/bin/mvn
├── mysql-8.4.13/bin/               # mysqld、mysql、mysqladmin
└── redis-7.4.4/src/               # redis-server、redis-cli
~~~

这些是原本机使用的目录示例；脚本支持上述同系列版本。运行包、依赖和数据库没有上传，首次克隆需要先准备环境，不能直接把根目录启动脚本当作自动安装器。

### 2. 启动后端

环境准备完成后，从仓库根目录执行：

~~~bash
python3 ruoyi-vue-pro/.local-dev/manage.py init
python3 ruoyi-vue-pro/.local-dev/manage.py build
python3 ruoyi-vue-pro/.local-dev/manage.py start
python3 ruoyi-vue-pro/.local-dev/verify_backend.py
~~~

- `init` 在独立空库中初始化演示数据，并生成本机数据库和 Redis 凭证。
- `build` 构建后端；`start` 启动本地服务并检查模板接口。
- `verify_backend.py` 检查模板、分类、商品列表、三款商品详情及价格数据；原工作区的 7 项检查均已通过。
- 查看状态或停止服务，将命令末尾改为 `status` 或 `stop`；停止服务保留数据。

| 配置 | 默认值 |
|---|---|
| 小程序 API | `http://127.0.0.1:48080/app-api` |
| 管理后台 API | `http://127.0.0.1:48080/admin-api` |
| 本地租户 ID | `1` |
| MySQL / Redis 端口 | `13306` / `16379` |
| 演示图片服务 | `http://127.0.0.1:48081` |

服务仅在本机运行。租户 `1` 是自己系统内的数据编号，不需要向开源作者申请。

### 3. 运行小程序

~~~bash
cd yudao-mall-uniapp
cp .env.example .env
npm install
~~~

1. HBuilderX 打开 **`yudao-mall-uniapp/` 源码根目录**，配置自己有开发权限的 AppID，或使用微信工具的测试号。
2. 选择“运行 → 运行到小程序模拟器 → 微信开发者工具”。
3. 手工导入时，微信工具选择 **`yudao-mall-uniapp/unpackage/dist/dev/mp-weixin/`**。

注意区分源码目录与编译输出；`mp-weixin/` 不应再次作为 HBuilderX 源项目编译。看到 Hello World 通常表示仍打开着微信默认示例。

### 4. 管理后台（可选）

~~~bash
cd yudao-ui-admin-vue3
cp .env.example .env
cp .env.local.example .env.local
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1
~~~

默认端口为 `3000`。示例环境中的租户名称和账号预填值需要与自己的数据库匹配，完整后台操作尚未在本项目中验收。

## 演示数据与开发边界

演示商品、价格和库存均明确标注为测试值，不对应真实货盘。开发业务表根据公开 Java 实体生成，未使用官方受限商城 SQL，也不代表生产数据库设计已完成。

本地展示接口通过，不等于真实微信登录、优惠券核销、付款或发货已经完成。后续会按“原版功能验收 → 页面与接口对照 → 逐页改 UI → 接入真实业务”的顺序推进。

更详细的数据与检查方法见 [本地演示说明](ruoyi-vue-pro/.local-dev/bootstrap/LOCAL-DEMO-VALIDATION.md)。新机器恢复后应重新运行验证脚本。

## 来源与配置

上游仓库、固定提交和下载范围见 [SOURCE_PROVENANCE.json](SOURCE_PROVENANCE.json)。各子项目保留自己的 LICENSE；此仓库是源码快照，未合并上游 Git 历史。

真实环境文件、运行密码、数据库、日志及缓存不上传。请按 `.example` 模板创建本机配置；启用加密或外部服务时，另行提供对应环境变量。上游 AI / IoT 集成测试中的字面量凭证已改为 `NAVIO_TEST_*` 变量。
