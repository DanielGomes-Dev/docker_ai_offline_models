"""Caracterização de src/utils/files.py (cópia local e enxuta do FilesUtils).

Atenção: difere do `platform_core.files.FilesUtils` — aqui não há flag
`overwrite`: um arquivo existente é sempre sobrescrito.
"""

import pytest

from src.utils.files import FilesUtils


class FakeUploadFile:
    """Imita o `UploadFile` do FastAPI: `filename` + `async read(n)`; registra os tamanhos pedidos."""

    def __init__(self, filename, content: bytes):
        self.filename = filename
        self._content = content
        self._offset = 0
        self.read_sizes: list[int] = []

    async def read(self, n: int = -1) -> bytes:
        self.read_sizes.append(n)
        chunk = self._content[self._offset : self._offset + n]
        self._offset += len(chunk)
        return chunk


@pytest.fixture
def files_utils():
    return FilesUtils()


class TestSaveUploadFile:
    async def test_should_write_the_upload_content_and_return_the_path(self, files_utils, tmp_path):
        path = await files_utils.save_upload_file(FakeUploadFile("audio.mp3", b"abc"), str(tmp_path))
        assert path == tmp_path / "audio.mp3"
        assert path.read_bytes() == b"abc"

    async def test_should_create_missing_nested_directories(self, files_utils, tmp_path):
        dest = tmp_path / "a" / "b"
        await files_utils.save_upload_file(FakeUploadFile("x.bin", b"x"), str(dest))
        assert dest.is_dir()

    async def test_should_accept_a_path_object_as_output_dir(self, files_utils, tmp_path):
        path = await files_utils.save_upload_file(FakeUploadFile("x.bin", b"x"), tmp_path)
        assert path == tmp_path / "x.bin"

    async def test_should_use_the_explicit_file_name_when_given(self, files_utils, tmp_path):
        path = await files_utils.save_upload_file(
            FakeUploadFile("cliente.wav", b"x"), str(tmp_path), file_name="interno.wav"
        )
        assert path == tmp_path / "interno.wav"
        assert not (tmp_path / "cliente.wav").exists()

    async def test_should_strip_directories_from_the_client_filename(self, files_utils, tmp_path):
        path = await files_utils.save_upload_file(FakeUploadFile("../../etc/passwd", b"x"), str(tmp_path))
        assert path == tmp_path / "passwd"

    async def test_should_overwrite_an_existing_file(self, files_utils, tmp_path):
        (tmp_path / "v.mp4").write_bytes(b"original")
        path = await files_utils.save_upload_file(FakeUploadFile("v.mp4", b"novo"), str(tmp_path))
        assert path.read_bytes() == b"novo"

    async def test_should_stream_in_1mb_chunks_until_empty_read(self, files_utils, tmp_path):
        size = 1024 * 1024
        content = b"a" * size + b"b" * size + b"c" * 10
        upload = FakeUploadFile("big.bin", content)
        path = await files_utils.save_upload_file(upload, str(tmp_path))
        assert path.read_bytes() == content
        assert upload.read_sizes == [size, size, size, size]  # 3 chunks + leitura vazia final

    async def test_should_create_an_empty_file_for_an_empty_upload(self, files_utils, tmp_path):
        path = await files_utils.save_upload_file(FakeUploadFile("vazio.txt", b""), str(tmp_path))
        assert path.exists()
        assert path.read_bytes() == b""
