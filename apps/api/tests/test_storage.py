"""Storage 抽象层测试。

设计原则(计划关键约束 5):一刀切走 minio,不留 local 分支。
测试用 MagicMock 桩 minio client,不真实连容器,保证单测可移植。
"""
from io import BytesIO
from unittest.mock import MagicMock

import pytest

from app.core.storage import MinioStorage, Storage


def _make_storage(buckets=None) -> MinioStorage:
    """构造 MinioStorage 但跳过 _ensure_buckets(避免短 bucket 名被 SDK 拒)。

    单测只关心 put/get/delete/stat/copy 的方法逻辑,不关心 bucket 自动创建
    (那是启动期的副作用,集成验证在端到端覆盖)。
    """
    buckets = buckets or {"personal": "tiangong-personal", "global": "tiangong-global"}
    obj = object.__new__(MinioStorage)
    obj._buckets = buckets
    obj._client = MagicMock()
    return obj


def test_storage_is_protocol():
    """Storage 是 Protocol,仅作类型约束,不应可实例化。"""
    with pytest.raises(TypeError):
        Storage()  # type: ignore[abstract]


def test_minio_storage_put_get_roundtrip():
    """put 写入,get 读回,内容一致。"""
    storage = _make_storage()
    storage._client.get_object.return_value = MagicMock(
        read=lambda: b"hello", close=lambda: None, release_conn=lambda: None,
    )
    storage.put("personal", "k1", b"hello", "text/plain")
    storage._client.put_object.assert_called_once()
    assert storage.get("personal", "k1") == b"hello"


def test_minio_storage_delete_idempotent_on_missing():
    """删除不存在的对象不抛错(minio NoSuchObject 视为已删除)。"""
    from minio.error import S3Error

    storage = _make_storage()
    storage._client.remove_object.side_effect = S3Error(
        code="NoSuchObject", message="no such", resource="r", request_id="x",
        host_id="h", response=None,
    )
    storage.delete("personal", "missing")  # 不抛即通过


def test_minio_storage_copy_cross_bucket():
    """copy 跨 bucket 复制(审核通过时 personal→global 用)。"""
    storage = _make_storage()
    storage.copy("personal", "src", "global", "dst")
    storage._client.copy_object.assert_called_once()
    args = storage._client.copy_object.call_args
    assert args.args[0] == "tiangong-global"  # 解析后的真实 bucket 名
    assert args.args[1] == "dst"


def test_minio_storage_stat_exists():
    """stat 返回对象是否存在。"""
    storage = _make_storage()
    storage._client.stat_object.return_value = MagicMock()
    assert storage.stat("personal", "k") is True

    from minio.error import S3Error
    storage._client.stat_object.side_effect = S3Error(
        code="NoSuchKey", message="no", resource="r", request_id="x",
        host_id="h", response=None,
    )
    assert storage.stat("personal", "k") is False
