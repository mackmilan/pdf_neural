from __future__ import annotations

import json
import mimetypes
import shutil
import tempfile
import urllib.parse
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from converter import convert

ROOT = Path(__file__).parent.resolve()
JOBS = ROOT / "output" / "jobs"
STATIC = ROOT / "static"
JOBS.mkdir(parents=True, exist_ok=True)


def multipart_file(content_type: str, body: bytes) -> tuple[str, bytes]:
    marker = "boundary="
    if marker not in content_type:
        raise ValueError("Requisicao multipart invalida")
    boundary = content_type.split(marker, 1)[1].strip().strip('"').encode()
    for part in body.split(b"--" + boundary):
        head, sep, data = part.partition(b"\r\n\r\n")
        if sep and b'name="pdf"' in head:
            filename = head.split(b"filename=", 1)[-1].split(b"\r\n", 1)[0].strip(b'"').decode("utf-8", "replace")
            return Path(filename).name, data.rstrip(b"\r\n-")
    raise ValueError("Arquivo PDF nao encontrado")


class Handler(BaseHTTPRequestHandler):
    def send_file(self, path: Path, disposition: str | None = None) -> None:
        if not path.is_file():
            self.send_error(404); return
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.send_header("Content-Length", str(path.stat().st_size)); self.end_headers()
        with path.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile)

    def do_GET(self) -> None:
        path = urllib.parse.unquote(self.path.split("?", 1)[0])
        if path == "/":
            return self.send_file(STATIC / "index.html")
        parts = Path(path.lstrip("/")).parts
        if len(parts) >= 3 and parts[0] == "jobs" and all(p not in ("..", ".") for p in parts):
            return self.send_file(JOBS.joinpath(*parts[1:]))
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path != "/api/convert":
            self.send_error(404); return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 30 * 1024 * 1024:
                raise ValueError("O limite e 30 MB")
            name, data = multipart_file(self.headers.get("Content-Type", ""), self.rfile.read(length))
            if not data.startswith(b"%PDF"):
                raise ValueError("O arquivo enviado nao e um PDF valido")
            job = uuid.uuid4().hex
            work = JOBS / job; work.mkdir()
            source = work / (Path(name).stem + ".pdf"); source.write_bytes(data)
            result = convert(source, work / "html")
            archive = work / "resultado.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                for file in result.rglob("*"):
                    if file.is_file(): zf.write(file, file.relative_to(result))
            fields = json.loads((result / "fields.json").read_text(encoding="utf-8"))
            payload = json.dumps({"preview": f"/jobs/{job}/html/index.html", "download": f"/jobs/{job}/resultado.zip", "fields": fields}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)
        except Exception as exc:
            payload = json.dumps({"error": str(exc)}).encode()
            self.send_response(400); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(payload)


if __name__ == "__main__":
    print("PDF Neural em http://127.0.0.1:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()

