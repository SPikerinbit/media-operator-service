# Media Operator 0.5.0 — Windows 10 安装包说明

此安装包与正式 **Windows 11** 版（`MediaOperatorSetup.exe`）使用**同一套冻结运行时**，仅将 Inno Setup 的最低系统版本降为 **Windows 10 x64（10.0.19041 及以上）**。

## 测试状态

**未在多种 Windows 10 版本与硬件组合上做过严格回归。** 本机在 Windows 11 上验证的是 Win11 门槛安装包；Win10 包仅在构建机上通过安装器编译与 SHA 校验，**不代表已在 Win10 实机完成全流程验收**。

使用前请自行确认：

- 已安装或可由安装程序补齐 **WebView2** 运行库；
- 显卡驱动与可选 NVIDIA 运行库满足转录/编码需求；
- 覆盖安装前退出 `MediaOperator` 与 `MediaWhisper`。

若遇到问题，可改用 [v0.5.0](https://github.com/SPikerinbit/media-operator-service/releases/tag/v0.5.0) 的 Windows 11 安装包（`MinVersion=10.0.22000`），或在 Win10 上反馈具体版本与日志。
