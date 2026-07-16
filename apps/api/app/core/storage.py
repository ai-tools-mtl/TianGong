"""统一对象存储抽象层。

设计决策(计划关键约束 5):一刀切走 minio,不保留 local 分支开关。
- Storage 是 Protocol,仅作类型约束,便于 service 层注入(mock 测试友好)
- MinioStorage 是唯一生产实现
- 测试通过 conftest 的 autouse fixture monkeypatch get_storage 返回内存假实现
"""
from io import BytesIO
from typing import Protocol

from loguru import logger
from minio import Minio
from minio.error import S3Error


class Storage(Protocol):
    """对象存储统一接口。bucket 取值:'personal' / 'global'(由 Settings 映射)。"""

    def put(self, bucket: str, key: str, content: bytes, content_type: str) -> None: ...
    def get(self, bucket: str, key: str) -> bytes: ...
    def delete(self, bucket: str, key: str) -> None: ...
    def stat(self, bucket: str, key: str) -> bool: ...
    def copy(
        self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str
    ) -> None: ...


class MinioStorage:
    """S3 兼容(minio)实现。构造时自动建 bucket(幂等)。"""

    def __init__(
        self, *, endpoint: str, access_key: str, secret_key: str,
        secure: bool, buckets: dict[str, str],
    ):
        self._buckets = buckets
        self._client = Minio(
            endpoint, access_key=access_key, secret_key=secret_key, secure=secure
        )
        self._ensure_buckets()

    def _ensure_buckets(self) -> None:
        """启动时自动建 bucket(不存在才建,幂等)。"""
        for name in self._buckets.values():
            if not self._client.bucket_exists(name):
                self._client.make_bucket(name)
                logger.info("created minio bucket {}", name)

    def _resolve(self, bucket_alias: str) -> str:
        """把 'personal'/'global' 别名解析成真实 bucket 名。"""
        try:
            return self._buckets[bucket_alias]
        except KeyError:
            raise ValueError(f"未知 bucket 别名: {bucket_alias}") from None

    def put(self, bucket: str, key: str, content: bytes, content_type: str) -> None:
        real = self._resolve(bucket)
        self._client.put_object(
            real, key, BytesIO(content), length=len(content),
            content_type=content_type,
        )

    def get(self, bucket: str, key: str) -> bytes:
        real = self._resolve(bucket)
        obj = self._client.get_object(real, key)
        try:
            return obj.read()
        finally:
            obj.close()
            obj.release_conn()

    def delete(self, bucket: str, key: str) -> None:
        """幂等:对象不存在视为已删除,不抛错。"""
        real = self._resolve(bucket)
        try:
            self._client.remove_object(real, key)
        except S3Error as e:
            # NoSuchObject/NoSuchKey 表示已不在,幂等成功
            if e.code in ("NoSuchObject", "NoSuchKey"):
                return
            raise

    def stat(self, bucket: str, key: str) -> bool:
        real = self._resolve(bucket)
        try:
            self._client.stat_object(real, key)
            return True
        except S3Error:
            return False

    def copy(
        self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str
    ) -> None:
        """跨 bucket 复制对象(审核通过 personal→global 用)。"""
        src_real = self._resolve(src_bucket)
        dst_real = self._resolve(dst_bucket)
        # minio copy_object 第二参为 "源bucket/源key" 形式的 Source
        self._client.copy_object(dst_real, dst_key, f"{src_real}/{src_key}")


_storage_singleton: Storage | None = None


def get_storage() -> Storage:
    """模块级单例。所有 service 通过依赖注入拿到 storage 实例。

    测试在 conftest 里 monkeypatch 本函数返回内存假实现,不真实连 minio。
    """
    global _storage_singleton
    if _storage_singleton is not None:
        return _storage_singleton

    from app.core.config import get_settings

    s = get_settings()
    _storage_singleton = MinioStorage(
        endpoint=s.minio_endpoint,
        access_key=s.minio_access_key,
        secret_key=s.minio_secret_key,
        secure=s.minio_secure,
        buckets={
            "personal": s.minio_bucket_personal,
            "global": s.minio_bucket_global,
        },
    )
    return _storage_singleton
