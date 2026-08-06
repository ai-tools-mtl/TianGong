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

# 1. dbus：建 socket 目录 + 起 system bus
mkdir -p /run/dbus
dbus-daemon --system --fork

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
