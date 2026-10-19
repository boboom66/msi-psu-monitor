# 测试用例（第二阶段）

- 基线提交：`650076a`；当前修复后工作树：Phase 2（见 git log）。
- 全量自动化用例由 `pytest --collect-only` 收集，当前 **645** 个；本文件记录本轮新增/关键用例、
  人工 E2E 用例和仍无法执行的真机/root 用例。
- 状态：PASS 已实际执行且符合预期；FAIL 已实际执行且不符合；BLOCKED 环境/权限/硬件限制；
  NOT RUN 尚未执行；N/A 不适用。

## A. 新增自动化用例

| ID | FUNC | 目的 | 输入/步骤 | 预期 | 实际 | 状态 |
|---|---|---|---|---|---|---|
| TEST-001 | FUNC-001/004/005 | 真实 console 入口版本/帮助 | `python -m msi_psu_monitor --version`；`--help` | `msi-psu-monitor 1.0.0`；exit 0；列出控制参数 | 均通过 | PASS |
| TEST-002 | FUNC-006/007/013/014 | 子进程 demo text/JSON | `MSI_PSU_DEMO=1 ... --once`；`-f json` | exit 0；文本含机型；JSON 可解析且 product 正确 | 通过 | PASS |
| TEST-003 | FUNC-033/020 | 告警退出码与 `--no-alerts` | 注入 `ocp_pin1`；`--no-alerts` | exit 2 + stderr ALERT；`--no-alerts` exit 0 无 ALERT | 通过 | PASS |
| TEST-004 | FUNC-011/012 | `-O` 文件输出 | `-f json -O file`；`--show-alert-log -O file` | 文件内容正确、exit 0 | 通过 | PASS |
| TEST-005 | FUNC-022 | AlertLog 查看器 | 空日志；预写一行 `append_alert_log` 后查看 | 空提示；预写行可读 | 通过 | PASS |
| TEST-006 | FUNC-044 | 无 demo/无硬件错误 | 清空 demo 环境变量后 `--once`（无 hidraw 时） | exit 1、`MSI PSU not found`、无 traceback | 本机无 hidraw，通过 | PASS（有真机时 skip） |
| TEST-010 | FUNC-080 | E0 短/垃圾帧 | 0–64B、全 0xFF、全 0xFE、递增字节 | 不抛异常；短帧不产生核心读数 | 通过 | PASS |
| TEST-011 | FUNC-073 | E1h 短/垃圾位图 | 0/1/3/18B、0xFF、递增 | 不抛异常；返回 None/dict | 通过 | PASS |
| TEST-012 | FUNC-074/075 | C0/C1 短帧 | 7/8/41/42B、垃圾 | 不抛异常；None/dict | 通过 | PASS |
| TEST-013 | FUNC-077/078 | 41h/42h 短帧 | 0–6B、垃圾 | 不抛异常；None/tuple | 通过 | PASS |
| TEST-014 | FUNC-076 | 短黑盒记录 | 3B 记录 | 跳过该记录，不伪造 | 通过 | PASS |
| TEST-015 | FUNC-160 | 非 loopback Host | 原始 socket `Host: evil.example` | HTTP 421 | 修复后 421 | PASS（修复） |
| TEST-016 | FUNC-160 | loopback Host 放行 | `127.0.0.1:port`、`localhost:port`、`[::1]:port` | HTTP 200 | 通过 | PASS |
| TEST-017 | FUNC-150 | 安全响应头 | GET `/`、`/api/state`、`/api/history` | nosniff/DENY/no-referrer/CSP/Permissions-Policy | 通过 | PASS |
| TEST-018 | FUNC-158 | 内嵌 JS 语法 | 提取 `<script>`，`node --check` | exit 0 | 通过 | PASS |
| TEST-019 | FUNC-137 | daemon fd 泄漏 | 300 次迭代，比较 `/proc/self/fd` | fd 不增长（≤+3） | 通过 | PASS |
| TEST-020 | FUNC-130 | daemon 迭代参数边界 | `--iterations 0/-1` | argparse exit 2 | 通过 | PASS（新增校验） |

## B. 构建/发布用例

| ID | FUNC | 目的 | 命令 | 预期 | 实际 | 状态 |
|---|---|---|---|---|---|---|
| TEST-030 | FUNC-190 | 源码 `.deb` | `bash scripts/build_deb.sh`（smoke 内） | 产物存在、权限 0644、config 存在 | 通过 | PASS |
| TEST-031 | FUNC-191 | 自包含 tar.gz | Phase 3：22.04 chroot 构建；clean-env `--version/--once`、新命令 smoke | 产物可运行、无 libpython、冻结 smoke 通过 | 通过（本地 chroot） | PASS（本地）/CI NOT RUN |
| TEST-032 | FUNC-192 | 零 Python `.deb` | `bash scripts/build_deb_binary.sh` + `dpkg-deb -f` | `Depends` 仅 libc6/zlib1g | 通过 | PASS（本机） |
| TEST-036 | FUNC-193/196 | 硬件验收 kit | `build_hardware_kit.sh`；提取后 `setup.sh`（二进制/源码）+ `acceptance.sh --demo` | kit 打包、安装命名空间、demo 验收、证据 tar | 通过 | PASS |
| TEST-033b | FUNC-193 | 安装/卸载（用户命名空间） | unshare + 临时 /etc/var/lib + fake systemctl/udevadm | 配置保留、`--purge` 删除、unit/udev 安装 | 通过 | PASS |
| TEST-033 | FUNC-196 | SBOM | `python3 scripts/build_sbom.py ...` | CycloneDX 1.5、产物哈希、9 组件 | 通过 | PASS |
| TEST-034 | FUNC-197 | release workflow | 静态审查 + `tests/test_release_security.py` | SBOM/上传/校验和存在 | 通过（未实际发版） | PARTIAL |

## C. 无法执行/阻塞用例

| ID | FUNC | 目的 | 阻塞原因 | 状态 |
|---|---|---|---|---|
| TEST-043b | FUNC-194/195 | 真实 systemd/udev 行为 | 仅 fake 通过，真实设备未验证 | PARTIAL |
| TEST-040 | FUNC-040–050 | 真实 hidraw 打开/发现/权限/flock | 无 `/dev/hidraw*` | BLOCKED |
| TEST-041 | FUNC-060–079 | 真实 E0/E1/C0/C1/黑盒/风扇/VIN | 无 PSU 硬件 | BLOCKED |
| TEST-042 | FUNC-090–096 | 真实风扇/Zero Fan/蜂鸣器/多轨写 | 无 PSU + 写入安全确认 | BLOCKED |
| TEST-043 | FUNC-193/194/195 | 安装/卸载/udev/systemd 实际启停 | 无免密 sudo/root | BLOCKED |
| TEST-044 | FUNC-191/192 | Ubuntu 22.04/glibc 2.35 构建 | 22.04.5 rootfs + userns chroot + PyInstaller 6.16.0 | 22.04 内运行、冻结 smoke、deb 依赖通过 | 通过（本地 chroot） | PASS（本地）/CI NOT RUN |
| TEST-045 | FUNC-191/192 | arm64 构建/运行 | 无 arm64 环境 | BLOCKED |
| TEST-046 | FUNC-158/159 | 真实浏览器图表/PNG/CSV/1s live | 无浏览器自动化 | NOT RUN |
| TEST-047 | FUNC-139 | 24h/72h 长稳/内存 | 未运行长测 | NOT RUN |
| TEST-048 | FUNC-197 | 真实 tag 发布/下载/升级/回滚 | 未 push tag | NOT RUN |

## D. 已有自动化覆盖

原有 645 个 pytest 用例（含本文件列出的新增项）由 `tests/` 直接执行；逐项结果以
`pytest -q` 的实际输出为准，不在此重复伪造逐条结果。测试模块与覆盖范围见
[test-plan.md](test-plan.md) §4 和 [test-report.md](test-report.md)。

## E. Phase 3 新增回归用例（2026-10-19）

| ID | FUNC | 目的 | 输入/步骤 | 预期 | 实际 | 状态 |
|---|---|---|---|---|---|---|
| TEST-049 | FUNC-001/004 | 输出路径失败诊断 | `--show-alert-log -O <blocker>/x`；`--once -O <blocker>/x`；`--show-log -O ...` | exit 1、stderr 含 cannot write、不含 Run as root/Traceback | 通过 | PASS |
| TEST-050 | FUNC-001/004 | stdout ENOSPC | `--show-alert-log` / `--export` / `--once` > `/dev/full` | exit 1、无 Traceback/Exception ignored、stderr 说明 | 通过 | PASS |
| TEST-051 | FUNC-023 | 非正 interval | `[monitor] interval = 0/-2/-0.5` 后裸 `--watch` | 回落 2.0，不忙循环/不抛 sleep | 通过 | PASS |
| TEST-052 | FUNC-012 | performance 配置语义 | `[fan] mode=performance duty=60` | fan_mode=performance、fan_duty=None | 通过 | PASS |
| TEST-053 | FUNC-026 | `--columns all` 拼写错误 | `parse_columns('all,wattage')` 与 CLI | ValueError / exit 1 | 通过 | PASS |
| TEST-054 | FUNC-022 | AlertLog limit=0 | `iter_alert_log(limit=0)` 有记录时 | 返回 [] | 通过 | PASS |
| TEST-055 | FUNC-130/137 | daemon 初始化失败资源 | open 成功、init 抛 OSError | 返回 None 且 psu.closed=True | 通过 | PASS |
| TEST-056 | FUNC-160 | Dashboard CSV 引号 | 历史值含逗号时 `/api/export` | 单元格被 `"..."` 引用，列数不变 | 通过 | PASS |

| TEST-057 | FUNC-158/159 | 真实 headless Chromium Dashboard | Playwright 打开 `/`，等待数据；检查标题/product/8 canvas、CSV/PNG 下载、console/page error、外部请求 | 页面有数据、CSV/PNG 有效、无错误/外部请求 | 通过（本机 headless） | PASS |

| TEST-058 | FUNC-158 | Dashboard 窄视口 | Playwright 320/768/1920px；检查 `scrollWidth`、8 canvas | 320 无横向溢出；图表仍渲染 | 通过（headless） | PASS |
| TEST-059 | FUNC-137 | 加速长稳 | demo daemon 20,000 样本，5s 采样 RSS/fd/state/prom/history | RSS 稳定、fd 不增长、无 traceback、正常退出 | 通过（约 200s） | PASS（加速）/24h NOT RUN |

| TEST-060 | FUNC-191/192 | Ubuntu 22.04 本地构建 | 22.04 rootfs + userns chroot + PyInstaller 6.16.0；chroot 内运行 + 冻结 smoke | 22.04 内 `--version/--once/--show-alert-log` 通过；deb 依赖仅 libc6>=2.35/zlib1g | 通过（本地 chroot） | PASS（本地）/CI NOT RUN |

| TEST-061 | FUNC-191/197 | CI release | push tag v1.0.0；build x86_64 + ubuntu-22.04-arm + publish | 两个 build success、release 发布、SHA256SUMS 覆盖全部资产 | 通过（run 39208968894） | PASS |
| TEST-062 | FUNC-191/192 | 发布不含 source deb | 检查 release 资产与 SHA256SUMS | 无 `_all.deb`（Depends python3），仅自包含 amd64/arm64 deb | 通过 | PASS（DEF-013） |

| TEST-063 | FUNC-025 | export 原子写 | 目标已有文件，`_write_csv` 写一半抛 ENOSPC | 目标仍是旧内容、scratch 被清理 | 通过 | PASS（DEF-015） |
| TEST-064 | FUNC-001/026 | 被忽略参数拒绝 | export + `-f json`/`--serial`；控制写 + `-f json` | argparse exit 2，错误说明 does not apply | 通过 | PASS（DEF-016） |
| TEST-065 | FUNC-023 | 配置 format 固定模式 | 配置 `format=json` + `--fan-mode auto` | 文本输出 + warning | 通过 | PASS（DEF-016） |

| TEST-066 | FUNC-130/137 | daemon 非 OSError 异常 | 注入 get_sensors/open/apply_stats/history/prom ValueError | 记录错误、计为失败/重试，不杀进程 | 通过 | PASS（DEF-017） |
| TEST-067 | FUNC-024 | 0 W 样本 | demo 样本 power=0/efficiency=0 | count 增加、avg=0 | 通过 | PASS（DEF-018） |
| TEST-068 | FUNC-023 | 默认 state dir 是文件 | DEFAULT_STATE_DIR=普通文件 + XDG | 回退 XDG，不使用文件 | 通过 | PASS（DEF-019） |
| TEST-069 | FUNC-001 | 空 serial | `--serial ''` | argparse exit 2 | 通过 | PASS（DEF-020） |

| TEST-070 | FUNC-044 | serial 发现异常设备 | fake MSIPSU.init 抛 ValueError | path=None、blocked 含设备、无 traceback | 通过 | PASS（DEF-021） |
