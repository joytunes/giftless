"""Basic Streaming Transfer Adapter

This transfer adapter offers 'basic' transfers by streaming uploads / downloads
through the Git LFS HTTP server. It can use different storage backends (local,
cloud, ...).
"""

import os
import shutil
from typing import BinaryIO, Dict, Optional

from flask import url_for, request, Response

from gitlfs.server.transfer import TransferAdapter, ViewProvider
from gitlfs.server.util import get_callable
from gitlfs.server.view import BaseView
from gitlfs.server.exc import NotFound


class LocalStorage:
    """Local storage implementation

    # TODO: do we need directory hashing?
    #       seems to me that in a single org/repo prefix this is not needed as we do not expect
    #       thousands of files per repo or thousands or repos per org
    """
    def __init__(self, path: str = None):
        if path is None:
            path = 'lfs-storage'
        self.path = path
        self._create_path(self.path)

    def get(self, prefix: str, oid: str) -> BinaryIO:
        path = self._get_path(prefix, oid)
        if os.path.isfile(path):
            return open(path, 'br')
        else:
            raise NotFound("Requested object was not found")

    def put(self, prefix: str, oid: str, data_stream: BinaryIO) -> int:
        path = self._get_path(prefix, oid)
        directory = os.path.dirname(path)
        self._create_path(directory)
        with open(path, 'bw') as dest:
            shutil.copyfileobj(data_stream, dest)
            return dest.tell()

    def exists(self, prefix: str, oid: str) -> bool:
        return os.path.isfile(self._get_path(prefix, oid))

    def get_size(self, prefix: str, oid: str) -> int:
        if self.exists(prefix, oid):
            return os.path.getsize(self._get_path(prefix, oid))
        return 0

    def _get_path(self, prefix: str, oid: str) -> str:
        return os.path.join(self.path, prefix, oid)

    @staticmethod
    def _create_path(path):
        if not os.path.isdir(path):
            os.makedirs(path)


class ObjectsView(BaseView):

    route_base = '<organization>/<repo>/objects/storage'
    storage: LocalStorage

    def __init__(self, storage):
        self.storage = storage

    def put(self, organization, repo, oid):
        """Upload a file to local storage

        For now, I am not sure this actually streams chunked uploads without reading the entire
        content into memory. It seems that in order to support this, we will need to dive deeper
        into the WSGI Server -> Werkzeug -> Flask stack, and it may also depend on specific WSGI
        server implementation and even how a proxy (e.g. nginx) is configured.
        """
        stream = request.stream
        self.storage.put(prefix=f'{organization}/{repo}', oid=oid, data_stream=stream)
        return Response(status=200)

    def get(self, organization, repo, oid):
        """Get an file open file stream from local storage
        """
        path = os.path.join(organization, repo)
        if self.storage.exists(path, oid):
            file = self.storage.get(path, oid)
            return Response(file, direct_passthrough=True, status=200)
        else:
            raise NotFound("The object was not found")

    def verify(self, organization, repo):
        return ["local-base-verify", organization, repo]

    @classmethod
    def get_storage_url(cls, operation: str, organization: str, repo: str, oid: Optional[str] = None) -> str:
        """Get the URL for upload / download requests for this object
        """
        op_name = f'{cls.__name__}:{operation}'
        return url_for(op_name, organization=organization, repo=repo, oid=oid, _external=True)


class BasicStreamedTransferAdapter(TransferAdapter, ViewProvider):

    def __init__(self, storage: Optional[LocalStorage], action_lifetime: int):
        self.storage = storage
        self.action_lifetime = action_lifetime

    def upload(self, organization: str, repo: str, oid: str, size: int) -> Dict:
        response = {"oid": oid,
                    "size": size,
                    "authenticated": True}

        prefix = os.path.join(organization, repo)
        if not self.storage.exists(prefix, oid) or self.storage.get_size(prefix, oid) != size:
            response['actions'] = {
                "upload": {
                    "href": ObjectsView.get_storage_url('put', organization, repo, oid),
                    "header": {
                        "Authorization": "Basic yourmamaisauthorized"
                    },
                    "expires_in": self.action_lifetime
                },
                "verify": {
                    "href": ObjectsView.get_storage_url('verify', organization, repo),
                    "header": {
                        "Authorization": "Basic yourmamaisauthorized"
                    },
                    "expires_in": self.action_lifetime
                }
            }

        return response

    def download(self, organization: str, repo: str, oid: str, size: int) -> Dict:
        response = {"oid": oid,
                    "size": size}

        prefix = os.path.join(organization, repo)
        if not self.storage.exists(prefix, oid):
            response['error'] = {
                "code": 404,
                "message": "Object does not exist"
            }

        elif self.storage.get_size(prefix, oid) != size:
            response['error'] = {
                "code": 422,
                "message": "Object size does not match"
            }

        else:
            response.update({
                "authenticated": True,
                "actions": {
                    "download": {
                        "href": ObjectsView.get_storage_url('get', organization, repo, oid),
                        "header": {
                            "Authorization": "Basic yourmamaisauthorized"
                        },
                        "expires_in": self.action_lifetime
                    }
                }
            })

        return response

    def register_views(self, app):
        ObjectsView.register(app, init_argument=self.storage)


def factory(storage_class, storage_options, action_lifetime):
    """Factory for basic transfer adapter with local storage
    """
    storage = get_callable(storage_class, __name__)
    return BasicStreamedTransferAdapter(storage(**storage_options), action_lifetime)
