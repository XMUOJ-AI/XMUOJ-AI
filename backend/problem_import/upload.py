from django.core.files.uploadhandler import FileUploadHandler, StopUpload

from .archive import WEB_LIMIT


class BoundedUploadHandler(FileUploadHandler):
    """Stop multipart file streaming before Django writes an oversized temporary file."""
    def __init__(self, request):
        super().__init__(request)
        self.received = 0

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.received > WEB_LIMIT:
            self.request.problem_import_too_large = True
            raise StopUpload(connection_reset=True)
        return raw_data

    def file_complete(self, file_size):
        return None
