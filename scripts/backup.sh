#!/usr/bin/env bash
# 天工备份：postgres（pg_dump）+ miniodata 卷（tar）→ 按日期目录，保留最近 N 份。
# 在部署宿主机上运行（需 docker；凭据不需要——pg_dump 走容器内本地连接）。
#
# 用法：
#   ./scripts/backup.sh                     # 默认 ./backups/，保留 7 份
#   BACKUP_ROOT=/var/backups/tiangong KEEP=14 ./scripts/backup.sh
#
# 产物结构（restore.sh 消费同构）：
#   $BACKUP_ROOT/2026-08-25T03-00-05/
#     db.sql.gz          # pg_dump 纯 SQL（gzip），含 pgvector 扩展与全部业务表
#     minio-data.tgz     # miniodata 卷整卷 tar（附件对象全量）
#     manifest.txt       # 时间与参数快照
set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-./backups}"
KEEP="${KEEP:-7}"
POSTGRES_USER="${POSTGRES_USER:-tiangong}"
POSTGRES_DB="${POSTGRES_DB:-tiangong}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-tiangong-postgres}"
MINIO_CONTAINER="${MINIO_CONTAINER:-tiangong-minio}"
COMPOSE_FILE_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$COMPOSE_FILE_DIR"  # docker compose 按仓库根的 compose 文件找容器

stamp="$(date +%F_%H-%M-%S)"
dest="$BACKUP_ROOT/$stamp"
mkdir -p "$dest"

echo "==> 备份 postgres（$POSTGRES_DB）"
docker exec "$POSTGRES_CONTAINER" pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$dest/db.sql.gz"

echo "==> 备份 miniodata 卷（在线 tar，不停服）"
# 用 docker cp 进出容器而非 bind mount：Git Bash(MSYS) 对 -v 路径的自动转换
# 不可靠（实测挂载会静默失效），docker cp 对相对路径目标无此问题；Linux 上同样适用
tmpc="tiangong-backup-tmp-$$"
docker run --name "$tmpc" --volumes-from "$MINIO_CONTAINER" alpine \
  sh -c 'tar czf /tmp/minio-data.tgz -C /data .' >/dev/null 2>&1
docker cp "$tmpc:/tmp/minio-data.tgz" "$dest/minio-data.tgz"
docker rm "$tmpc" >/dev/null

{
  echo "created_at=$(date -Is)"
  echo "postgres=${POSTGRES_USER}@${POSTGRES_DB}"
  echo "db_rows=$(docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'") tables"
  echo "db_sql_gz=$(du -h "$dest/db.sql.gz" | cut -f1)"
  echo "minio_tgz=$(du -h "$dest/minio-data.tgz" | cut -f1)"
} > "$dest/manifest.txt"

echo "==> 轮转：保留最近 $KEEP 份"
# ls -1dt 列目录按 mtime 倒序；tail -n +N+1 取第 N+1 个起（即旧的）删除
ls -1dt "$BACKUP_ROOT"/*/ | tail -n +"$((KEEP + 1))" | while read -r old; do
  echo "    删除旧备份: $old"
  rm -rf "$old"
done

echo "✓ 备份完成: $dest"
cat "$dest/manifest.txt"
