"""Storage 抽象层测试。

设计原则(计划关键约束 5):一刀切走 minio,不留 local 分支。
测试 patch Minio 客户端类(而非绕开 __init__),让构造真实走 _ensure_buckets,
覆盖 bucket 自动创建逻辑 + put/get/delete/stat/copy 方法。
"""
from unittest.mock import MagicMock, patch

import pytest

from app.core import storage as storage_mod
from app.core.storage import MinioStorage, Storage

_BUCKETS = {"personal": "tiangong-personal", "global": "tiangong-global"}


def _make_storage_with_mock_client():
    """patch Minio 类,构造 MinioStorage 走真实 __init__(含 _ensure_buckets)。

    返回 (storage, mock_client)。mock_client 的 bucket_exists 默认返 False,
    验证 make_bucket 被调。
    """
    with patch.object(storage_mod, "Minio") as MockMinio:
        mock_client = MagicMock()
        mock_client.bucket_exists.return_value = False
        MockMinio.return_value = mock_client
        storage = MinioStorage(
            endpoint="localhost:9000", access_key="x", secret_key="y",
            secure=False, buckets=_BUCKETS,
        )
    return storage, mock_client


def test_storage_is_protocol():
    """Storage 是 Protocol,仅作类型约束,不应可实例化。"""
    with pytest.raises(TypeError):
        Storage()  # type: ignore[abstract]


def test_init_creates_missing_buckets():
    """构造时自动建 bucket(不存在的才建,幂等)。"""
    storage, mock_client = _make_storage_with_mock_client()
    # 两个 bucket 都不存在 → make_bucket 各调一次
    assert mock_client.make_bucket.call_count == 2
    called_names = {c.args[0] for c in mock_client.make_bucket.call_args_list}
    assert called_names == {"tiangong-personal", "tiangong-global"}


def test_init_skips_existing_buckets():
    """已存在的 bucket 不重复建(幂等)。"""
    with patch.object(storage_mod, "Minio") as MockMinio:
        mock_client = MagicMock()
        mock_client.bucket_exists.return_value = True  # 都已存在
        MockMinio.return_value = mock_client
        MinioStorage(
            endpoint="x", access_key="x", secret_key="x",
            secure=False, buckets=_BUCKETS,
        )
    mock_client.make_bucket.assert_not_called()


def test_minio_storage_put_get_roundtrip():
    """put 写入,get 读回,内容一致。"""
    storage, _ = _make_storage_with_mock_client()
    storage._client.get_object.return_value = MagicMock(
        read=lambda: b"hello", close=lambda: None, release_conn=lambda: None,
    )
    storage.put("personal", "k1", b"hello", "text/plain")
    storage._client.put_object.assert_called_once()
    assert storage.get("personal", "k1") == b"hello"


def test_minio_storage_delete_idempotent_on_missing():
    """删除不存在的对象不抛错(minio NoSuchObject 视为已删除)。"""
    from minio.error import S3Error

    storage, _ = _make_storage_with_mock_client()
    storage._client.remove_object.side_effect = S3Error(
        code="NoSuchObject", message="no such", resource="r", request_id="x",
        host_id="h", response=None,
    )
    storage.delete("personal", "missing")  # 不抛即通过


def test_minio_storage_delete_propagates_other_errors():
    """非 NoSuchObject 的 S3Error 仍上抛(不静默吞)。"""
    from minio.error import S3Error

    storage, _ = _make_storage_with_mock_client()
    storage._client.remove_object.side_effect = S3Error(
        code="AccessDenied", message="forbidden", resource="r", request_id="x",
        host_id="h", response=None,
    )
    with pytest.raises(S3Error):
        storage.delete("personal", "k")


def test_minio_storage_copy_cross_bucket():
    """copy 跨 bucket 复制(审核通过 personal→global 用)。"""
    storage, _ = _make_storage_with_mock_client()
    storage.copy("personal", "src", "global", "dst")
    storage._client.copy_object.assert_called_once()
    args = storage._client.copy_object.call_args
    assert args.args[0] == "tiangong-global"  # 解析后真实 bucket 名
    assert args.args[1] == "dst"
    assert args.args[2] == "tiangong-personal/src"


def test_minio_storage_resolve_unknown_bucket_raises():
    """未知 bucket 别名抛 ValueError。"""
    storage, _ = _make_storage_with_mock_client()
    with pytest.raises(ValueError, match="未知 bucket"):
        storage.put("unknown", "k", b"x", "text/plain")


def test_minio_storage_stat_exists():
    """stat 返回对象是否存在。"""
    storage, _ = _make_storage_with_mock_client()
    storage._client.stat_object.return_value = MagicMock()
    assert storage.stat("personal", "k") is True

    from minio.error import S3Error
    storage._client.stat_object.side_effect = S3Error(
        code="NoSuchKey", message="no", resource="r", request_id="x",
        host_id="h", response=None,
    )
    assert storage.stat("personal", "k") is False
