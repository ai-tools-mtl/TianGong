#!/bin/sh
# drawio 渲染服务启动脚本：起 dbus + 常驻 Xvfb，再 exec uvicorn。
#
# 三个 headless 运行依赖（缺任一 drawio 导出都会 Export failed）：
# 1. dbus-daemon：Chromium/Electron 异步操作依赖 session bus，缺失致导出失败
#    （实测：装 dbus 包但不起 daemon → 渲染 rc=1；起 daemon 后 rc=0）
# 2. Xvfb 常驻：Electron 需 X server；固定 DISPLAY=:42
# 3. 不用 xvfb-run 包裹 uvicorn（实测 xvfb-run 作 PID1 时 uvicorn 进程不启动）
# 参照 rlespinasse/docker-drawio-desktop-headless 的做法。
set -e

# 1. dbus：Chromium/Electron 需要两套 bus，缺任一会报
#    "Failed to connect to the bus: Could not parse server address"
#    - system bus：dbus-daemon --system（需要 /run/dbus 目录）
#    - session bus：dbus-launch（Chromium 实际连的是它，需 DBUS_SESSION_BUS_ADDRESS 环境变量）
mkdir -p /run/dbus
# 清理上次崩溃残留的 pid/socket：容器被 SIGKILL（restart 超时/WSL 重启）时
# dbus-daemon 来不及清理，pid 文件留在可写层，下次 dbus-daemon 拒启 → 容器死循环重启。
rm -f /run/dbus/pid /run/dbus/system_bus_socket
dbus-daemon --system --fork
# --sh-syntax 输出 "VAR='value'; export VAR;" 形式，eval 进当前 shell；双引号包裹命令替换
# 比裸 $(...) 更可靠。export 后 exec 的 uvicorn 及其 drawio 子进程继承该环境变量。
eval "$(dbus-launch --sh-syntax)"
echo "dbus session bus: ${DBUS_SESSION_BUS_ADDRESS:-未设置}"

# 2. Xvfb：固定 DISPLAY 常驻
export DISPLAY=":42"
Xvfb "${DISPLAY}" -screen 0 1280x1024x24 -nolisten unix -ac &
XVFB_PID=$!

# 等待 Xvfb 就绪（轮询 DISPLAY 可连）
for i in $(seq 1 20); do
  if xdpyinfo -display "${DISPLAY}" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
echo "Xvfb ready on ${DISPLAY} (pid ${XVFB_PID})"

# 3. exec 接管：uvicorn 成为 PID 1，直接收信号（docker stop 优雅关闭）
exec uvicorn main:app --host 0.0.0.0 --port 8001
