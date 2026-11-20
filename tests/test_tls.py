"""Verify TLS handshakes, not the eagerly loaded CA count."""
import http.server
import shlex
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from omyds.tools.run_command import command_argv, run_process, system_ca_bundle, SANDBOX_CA_FILE


class TLSTests(unittest.TestCase):
    def test_bundle_selection_follows_symlinks_and_skips_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cert = root / "public.pem"
            cert.write_text("test fixture")
            link = root / "bundle.pem"
            link.symlink_to(cert)
            with patch("omyds.tools.run_command.SYSTEM_CA_BUNDLES", [str(root / "missing"), str(link)]):
                self.assertEqual(system_ca_bundle(), cert)
            with patch("omyds.tools.run_command.SYSTEM_CA_BUNDLES", []):
                self.assertIsNone(system_ca_bundle())

    def test_offline_does_not_mount_ca_bundle(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch("omyds.tools.run_command.shutil.which", return_value="/usr/bin/bwrap"), \
             patch("omyds.tools.run_command.system_ca_bundle") as bundle:
            argv = command_argv("true", Path(tmp))
        bundle.assert_not_called()
        self.assertNotIn(SANDBOX_CA_FILE, argv)

    def test_real_sandbox_tls_accepts_trusted_and_rejects_untrusted_certificate(self):
        if not all(shutil.which(x) for x in ("bwrap", "openssl")) or not Path('/usr/bin/python3').exists():
            self.skipTest("需要 bwrap、openssl 和系统 Python")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / 'workspace'
            workspace.mkdir()
            probe = run_process(command_argv('true', workspace, network=True), workspace)
            if '退出码: 0' not in probe:
                self.skipTest('当前环境不能启动联网沙箱：' + probe[:160])
            cert, key = root / 'test-ca.pem', root / 'test-key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                            '-days', '1', '-subj', '/CN=localhost',
                            '-addext', 'subjectAltName=IP:127.0.0.1',
                            '-addext', 'basicConstraints=critical,CA:TRUE',
                            '-keyout', str(key), '-out', str(cert)],
                           check=True, capture_output=True, timeout=20)

            class Handler(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'TLS_TEST_ONLY')
                def log_message(self, *args):
                    pass

            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                script = (
                    'from pathlib import Path; import urllib.request; '
                    f'assert not Path({str(key)!r}).exists(); '
                    f"print(urllib.request.urlopen('https://127.0.0.1:{server.server_port}', timeout=3).read().decode())"
                )
                command = '/usr/bin/python3 -c ' + shlex.quote(script)
                with patch('omyds.tools.run_command.system_ca_bundle', return_value=cert):
                    trusted = run_process(command_argv(command, workspace, network=True), workspace)
                self.assertIn('退出码: 0', trusted)
                self.assertIn('TLS_TEST_ONLY', trusted)
                # No trust in the test certificate: the same request must fail verification.
                untrusted = run_process(command_argv(command, workspace, network=True), workspace)
                self.assertIn('CERTIFICATE_VERIFY_FAILED', untrusted)
                self.assertNotIn('TLS_TEST_ONLY', untrusted)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
