import os
from datetime import datetime, timedelta, timezone
from typing import Any, BinaryIO, Dict, Optional

from google.cloud import storage  # type: ignore
from google.cloud.exceptions import Conflict  # type: ignore

from giftless.transfer.basic_external import ExternalStorage
from giftless.transfer.basic_streaming import StreamingStorage
from giftless.transfer.exc import ObjectNotFound


class GoogleCloudBlobStorage(StreamingStorage, ExternalStorage):
    """Google Cloud Storage backend supporting direct-to-cloud
    transfers.

    """

    def __init__(self, bucket_name: str, account_json_path: str, path_prefix: Optional[str] = None, **_):
        self.bucket_name = bucket_name
        self.path_prefix = path_prefix
        self.storage_client = storage.Client.from_service_account_json(
            account_json_path)
        self._init_container()

    def get(self, prefix: str, oid: str) -> BinaryIO:
        bucket = self.storage_client.bucket(self.bucket_name)
        blob = bucket.blob(self._get_blob_path(prefix, oid))
        return blob.download_as_string()  # type: ignore

    def put(self, prefix: str, oid: str, data_stream: BinaryIO) -> int:
        bucket = self.storage_client.bucket(self.bucket_name)
        blob = bucket.blob(self._get_blob_path(prefix, oid))
        blob.upload_from_file(data_stream)
        return data_stream.tell()

    def exists(self, prefix: str, oid: str) -> bool:
        bucket = self.storage_client.bucket(self.bucket_name)
        blob = bucket.blob(self._get_blob_path(prefix, oid))
        return blob.exists()  # type: ignore

    def get_size(self, prefix: str, oid: str) -> int:
        bucket = self.storage_client.get_bucket(self.bucket_name)
        blob = bucket.blob(self._get_blob_path(prefix, oid))
        if blob.exists():
            return bucket.get_blob(self._get_blob_path(prefix, oid)).size  # type: ignore
        else:
            raise ObjectNotFound("Object does not exist")

    def get_upload_action(self, prefix: str, oid: str, size: int, expires_in: int,
                          extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        filename = extra.get('filename') if extra else None
        return {
            "actions": {
                "upload": {
                    "href": self._get_signed_url(prefix, oid, expires_in, filename),
                    "header": {
                        "x-ms-blob-type": "BlockBlob",
                    },
                    "expires_in": expires_in
                }
            }
        }

    def get_download_action(self, prefix: str, oid: str, size: int, expires_in: int,
                            extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        filename = extra.get('filename') if extra else None
        return {
            "actions": {
                "download": {
                    "href": self._get_signed_url(prefix, oid, expires_in, filename),
                    "header": {},
                    "expires_in": 900
                }
            }
        }

    def _get_blob_path(self, prefix: str, oid: str) -> str:
        """Get the path to a blob in storage
        """
        if not self.path_prefix:
            storage_prefix = ''
        elif self.path_prefix[0] == '/':
            storage_prefix = self.path_prefix[1:]
        else:
            storage_prefix = self.path_prefix
        return os.path.join(storage_prefix, prefix, oid)

    def _get_signed_url(self, prefix: str, oid: str, expires_in: int, filename: Optional[str] = None) -> str:
        bucket = self.storage_client.bucket(self.bucket_name)
        token_expires = (datetime.now(tz=timezone.utc) +
                         timedelta(seconds=expires_in))
        extra_args = {}
        if filename:
            extra_args['content_disposition'] = f'attachment; filename="{filename}"'

        url = bucket.generate_signed_url(
            expiration=token_expires, version='v4')
        return url  # type: ignore

    def _init_container(self):
        """Create the storage container
        """
        try:
            self.storage_client.create_bucket(self.bucket_name)
        except Conflict:
            pass
