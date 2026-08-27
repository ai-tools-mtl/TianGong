#!/usr/bin/env bash
# 天工恢复：从 backup.sh 产出的备份目录恢复 postgres + miniodata 卷。
# ⚠️ 破坏性操作——会 DROP 并重建目标数据库、清空 miniodata 卷。
# 在部署宿主机上运行。演练/实恢同一条路径。
#
# 用法：
#   ./scripts/restore.sh ./backups/2026-08-25_03-00-05 --yes
#   # 不带 --yes 只做预检（列出将执行的动作），不落任何改动。
set -euo pipefail

BACKUP_DIR="${1:-}"
CONFIRM="${2:-}"
POSTGRES_USER="${POSTGRES_USER:-tiangong}"
POSTGRES_DB="${POSTGRES_DB:-tiangong}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-tiangong-postgres}"
MINIO_CONTAINER="${MINIO_CONTAINER:-tiangong-minio}"
COMPOSE_FILE_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "$BACKUP_DIR" || ! -f "$BACKUP_DIR/db.sql.gz" || ! -f "$BACKUP_DIR/minio-data.tgz" ]]; then
  echo "用法: $0 <备份目录（含 db.sql.gz 与 minio-data.tgz）> [--yes]" >&2
  echo "示例: $0 ./backups/2026-08-25_03-00-05 --yes" >&2
  exit 1
fi

cd "$COMPOSE_FILE_DIR"
BACKUP_DIR="$(cd "$BACKUP_DIR" && pwd)"

echo "恢复源 : $BACKUP_DIR"
cat "$BACKUP_DIR/manifest.txt" 2>/dev/null || echo "(无 manifest)"
echo "目标   : postgres=$POSTGRES_DB  minio=$MINIO_CONTAINER（数据将被替换！）"

if [[ "$CONFIRM" != "--yes" ]]; then
  echo
  echo "预检模式（未做任何改动）。确认执行加 --yes。流程："
  echo "  1. docker compose stop api（防恢复期间写入）"
  echo "  2. DROP DATABASE $POSTGRES_DB; CREATE DATABASE ...; psql 导入 db.sql.gz"
  echo "  3. 清空 miniodata 卷并解包 minio-data.tgz"
  echo "  4. docker compose start api minio 重启"
  exit 0
fi

echo "==> [1/4] 停 api（防恢复期间写入）"
docker compose stop api

echo "==> [2/4] 重建并导入 postgres"
# 删活动连接（恢复时可能有残留连接）后 DROP/CREATE；pgvector 扩展随 dump 重建
docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d postgres \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$POSTGRES_DB' AND pid<>pg_backend_pid();" >/dev/null
docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d postgres \
  -c "DROP DATABASE IF EXISTS $POSTGRES_DB;" \
  -c "CREATE DATABASE $POSTGRES_DB;" >/dev/null
# ON_ERROR_STOP=1：SQL 出错即非零退出，配合 set -e 在清空 minio 卷（第 3 步）之前
# 中断——部分导入绝不能被当成恢复成功继续走完（psql 默认吞错仍返回 0）
gunzip -c "$BACKUP_DIR/db.sql.gz" | docker exec -i "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 >/dev/null

echo "==> [3/4] 恢复 miniodata 卷"
docker compose stop minio
# docker cp 进容器 + docker start 执行解包（同 backup.sh：绕开 Git Bash 的 -v 路径转换）
tmpc="tiangong-restore-tmp-$$"
docker create --name "$tmpc" --volumes-from "$MINIO_CONTAINER" alpine \
  sh -c 'find /data -mindepth 1 -delete && tar xzf /tmp/minio-data.tgz -C /data' >/dev/null
docker cp "$BACKUP_DIR/minio-data.tgz" "$tmpc:/tmp/minio-data.tgz"
docker start -a "$tmpc" >/dev/null
docker rm "$tmpc" >/dev/null

echo "==> [4/4] 重启服务"
docker compose start minio api

echo "✓ 恢复完成。验证建议：登录一次、打开任一项目确认章节与附图完整。"
