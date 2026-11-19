## 1. 项目文档

* Spring 文档：<http://doc.iocoder.cn/>
* Cloud 文档：<https://cloud.iocoder.cn/>

## 2. 前端预览

该项目，提前编译好了前端项目的静态资源，无需安装 Node 等前端环境，可以直接体验和使用。操作步骤如下：

在 [yudao-demo](https://gitee.com/yudaocode/yudao-demo) 项目中，提前编译好了前端项目的静态资源，无需安装 Node 等前端环境，可以直接体验和使用。操作步骤如下：

① 克隆 <https://gitee.com/yudaocode/yudao-demo> 项目，运行对应的启动类：

* [Vue3 + element-plus](https://github.com/yudaocode/yudao-ui-admin-vue3) ：ElementPlusApplication
* [Vue3 + vben](https://github.com/yudaocode/yudao-ui-admin-vben) ：VbenApplication
* [Vue2 + element-ui](https://github.com/yudaocode/yudao-ui-admin-vben) ：ElementUIApplication

② 访问 <http://127.0.0.1:2048/> 地址，即可看到对应的管理后台。

## 3. SSO 示例

① 基于授权码模式，实现 SSO 单点登录，参见 `yudao-sso-demo-by-code` 项目。

② 实战二：基于密码模式，实现 SSO 登录，参见 `yudao-sso-demo-by-password` 项目。

Spring Boot 配合 <https://doc.iocoder.cn/oauth2/> 文档，Spring Cloud 配合 <https://cloud.iocoder.cn/oauth2/> 文档。