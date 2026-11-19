# Changelog / 更新记录

README 保留稳定用法，本文件记录用户可感知的版本差异。
Stable usage belongs in the README; user-facing version changes belong here.

以下是开发版本记录，不表示已发布为 GitHub Release。
These entries describe development versions, not confirmed GitHub Releases.

## Unreleased / 未发布

### Documentation / 文档
- 新增对应的中文、英文 README，统一安装、权限、记忆与数据说明。
- 移除首页固定版本号、过时目录树与不准确的安全保证。
- Add matching Chinese and English READMEs covering setup, permissions, memory, and data.
- Remove the hard-coded homepage version, outdated source tree, and inaccurate security guarantees.

### v0.2.0 release preparation / 发布准备
- 计划以已有功能完成发布；发布前统一程序和包版本，验证干净安装、入口及本机 bwrap。
- Plan to release the existing feature set; align application/package versions and verify clean installation, entry points, and local bwrap before release.

## 0.1.9.12

### Added / 新增
- 工作区自动、逐次确认与显式宿主机模式，可切换并查看权限状态。
- 每次模型请求携带实时工作区与权限信息。
- 工具目的、预计影响及实际操作说明。
- Workspace, approval, and explicit host modes with local controls.
- Live workspace and permission context in each model request.
- Tool-purpose, expected-impact, and actual-operation descriptions.

### Changed / 调整
- 工作区命令保持隔离并免逐次确认；宿主机模式不自动授予 sudo/root。
- 历史按角色配色，精简提示，恢复 logo 颜色。
- Sandboxed workspace commands no longer require individual approvals; host mode does not automatically grant sudo/root.
- Color-coded history, shorter messages, and restored logo colors.

### Validation notes / 验证说明
- 开发环境：38 项测试通过；1 项真实 bwrap 测试因环境限制跳过。
- 用户提供的文件注入与假数据发送样本未观察到目标动作执行，不代表普遍防注入保证。
- 一次测试中模型为自证而扩大了文件搜索范围；任务范围约束仍值得改进。
- Development environment: 38 passing tests; one real bwrap test skipped due to environment restrictions.
- User-run injection and dummy-data transfer samples did not show targeted actions; this is not a general injection-resistance guarantee.
- One run expanded file searches unnecessarily to demonstrate non-execution; task-scope discipline remains an improvement area.

## 0.1.9.11

### Fixed / 修复
- 保留 reasoning_content，按完整轮次裁剪上下文，避免拆散工具调用与结果。
- 请求失败保留工具记录，支持继续请求。
- 修正越界授权、临时文件冲突和命令退出状态。
- Preserve reasoning_content and trim whole turns without splitting tool-call/result pairs.
- Retain tool records after request failures and support continuation.
- Fix outside-workspace approvals, temporary-file collisions, and command exit-status reporting.

### Changed / 调整
- 拆分入口、会话、模型循环、工具执行与界面。
- 增加返回会话菜单，补充构建入口，改善配色与帮助排版。
- Separate application lifecycle, model loop, tool execution, and UI.
- Add return-to-menu behavior and build entry-point configuration; improve colors and help layout.
