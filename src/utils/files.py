from pathlib import Path


class FilesUtils:
    async def save_upload_file(self, upload_file, output_dir, file_name=None) -> Path:
        """Salva um UploadFile no diretório informado (streaming, 1MB por chunk)."""
        folder = Path(output_dir)
        folder.mkdir(parents=True, exist_ok=True)

        filename = file_name or Path(upload_file.filename).name
        file_path = folder / filename

        with file_path.open("wb") as f:
            while True:
                chunk = await upload_file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)

        return file_path
