# AA 雷电安装包只读安全检查

2026-09-09。范围是安装元数据、权限、编译清单及文件共享路径；不是完整安全审计，
不是反作弊逆向或防封配置。没有读取账号数据库、口令、聊天、牌局私有数据、进程内存或网络载荷。

## 样本与环境

- 唯一连接实例：`emulator-5554`，操作明确指定该实例。
- 包名`com.plusaa.amula`；版本1.9.1，versionCode1，minSdk23 / targetSdk34。
- installer=`com.android.packageinstaller`：通过安装器安装，不证明发行商身份或安装包可信性。
- Android报告版本9，安全补丁2019-07-05。targetSdk34不代表底层Android已更新。
  该日期是系统自报信息，未审计模拟器厂商是否另有补丁。
- adb shell为uid2000，未提权；包UID10050，不能因清单内出现系统UID字符串就称其拥有系统权限。
- 已安装APK大小232136982字节；SHA256：
  `19ef4c3562dbcf8f3684651806391c9adf08bfce19b08d0b63376256e7b9c981`。
  系统记录APK签名方案v3，但没有可信发行商签名指纹作比对；文件哈希只是当前样本身份。
- 临时提取只包含已安装的base.apk，没有应用数据；使用雷电自带aapt解析清单和两个XML资源。

## 发现与限制

| 项目 | 实测 | 结论 |
|---|---|---|
| 调试构建 | 包flags无DEBUGGABLE，清单未启用debuggable | 未发现普通可调试构建标志；不代表不可逆向 |
| 系统备份 | allowBackup=true；Backup Manager当前disabled，无当前transport客户端 | 允许备份配置值得厂商审查，但没有证据正在云备份 |
| 明文流量 | usesCleartextTraffic=true，未见networkSecurityConfig属性 | 配置允许明文，不证明口令/牌局实际上明文传输；本次未抓包 |
| 权限 | 精确定位runtime granted=true；外部存储读写granted=false、USER_FIXED | AppOps的存储allow不能取代运行时授权，不能据此说全盘可读 |
| 其他敏感声明 | 相机、录音、电话、悬浮窗、安装包、查询应用等 | 声明不等于已授权或正在使用；部分权限是较新Android版本定义 |
| 特殊AppOps | 悬浮窗default；安装包default mode allow | 不足以单独确认设置页开关/实际使用，未擅自修改 |
| 文件提供器 | 所检查的FileProvider、UniWebView、NativeShare提供器exported=false | 不是任意外部应用都能直接读取，仍需审查URI授权路径 |
| 文件共享路径 | file_paths.xml与file_provider_paths.xml含external-path path="." | 范围较宽，是否可被滥用取决于URI授予与调用验证，未执行利用验证 |
| 导出组件 | 部分图片/图库/身份核验活动及腾讯会话服务exported=true | 有待厂商审查的IPC攻击面，不等于已经发现可利用漏洞 |
| 受权限保护组件 | ProfileInstallReceiver要求DUMP，KeepAliveJobService要求BIND_JOB_SERVICE | 不能把所有exported组件都当成无保护接口 |

清单还声明一个`EmulatorCheckService`，以及身份核验、统计、监控、客服/音视频等组件。
组件存在只证明打包/注册了相应入口，不证明其当前已执行，也不揭示封号判定规则。
没有关闭或修改任何这些组件，没有尝试绕过检查。

## 建议

1. 保留现有专用模拟器和最小应用集合；不要在Android客体/共享目录存密码、钱包文件或身份证原图。
2. 维持外部存储当前拒绝状态；定位、相机、麦克风可能关系到功能或合规核验，未经功能确认不强行收回。
3. 只通过核实的发行渠道更新。可请对方提供官方版本及签名信息，并明确模拟器/实时辅助政策。
4. 明文流量、备份和导出组件应由发行商审查修复；自行改Manifest、重签APK或禁用检测组件不属于本次防护。
5. 底层系统报告的补丁较旧，考虑厂商正式更新，但不能擅自升级/重装而影响账号登录及现有采集校准。

本次只做检查，未改权限、清单、系统配置或防火墙，未重启/登录/登出/进桌。
检查后AA主进程仍存在；没有通过界面确认具体登录或网络状态。
本记录不能用于承诺不封号、证明平台允许辅助，或将应用认定为恶意软件。

临时APK副本未上传。清理命令被执行环境策略阻止，没有重试绕过；副本仍位于
`C:/Users/Administrator/AppData/Local/Temp/aa-package-audit-ca7e5a22646849d8b4ebfd71eb1c2088/aa-installed.apk`。
它只是232136982字节的安装包副本，不含账号数据；如需释放空间可由用户手动删除该副本，
不会卸载模拟器内的AA。保留本报告中的SHA256作为本次审计样本标识。
