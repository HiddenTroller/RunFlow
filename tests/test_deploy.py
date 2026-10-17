import io
import json
import unittest
from unittest.mock import patch

import config
import main
from mfds_client import ServiceError
from public_limits import PublicRequestLimits


def handler(headers, path='/api/status', body=b''):
    h = object.__new__(main.Handler)
    h.headers, h.path, h.rfile, h.sent = headers, path, io.BytesIO(body), []
    h.send = lambda status, payload, *a: h.sent.append((status, payload, a))
    return h


class DeployTests(unittest.TestCase):
    def test_env_vars_used_only_without_env_file(self):
        with patch.dict('os.environ', {'MFDS_SERVICE_KEY': 'from-env'}), patch.object(config, 'ROOT', config.ROOT / 'missing'):
            self.assertEqual(config.settings()['MFDS_SERVICE_KEY'], 'from-env')

    def test_public_get_needs_no_password_and_keeps_keys_private(self):
        conf = {'APP_PASSWORD': 'old-password', 'UPSTAGE_API_KEY': 'private-key', 'MFDS_SERVICE_KEY': 'private-mfds'}
        with patch.multiple('main', ALLOWED_HOST='app.onrender.com', PUBLIC=True), patch('main.settings', return_value=conf):
            for route in ['/', '/api/status', '/brand-logo.png']:
                h = handler({'Host': 'app.onrender.com'}, route)
                h.do_GET()
                self.assertEqual(h.sent[0][0], 200)
                response = str(h.sent[0][1])
                for secret in conf.values():
                    self.assertNotIn(secret, response)
            self.assertEqual(h.sent[0][2][0], 'image/png')
            self.assertEqual(h.sent[0][1], (main.STATIC / 'brand-logo.png').read_bytes())

    def test_public_post_needs_https_origin_and_token(self):
        raw = json.dumps({'base64': 'eA==', 'consent': False}).encode()
        base = {'Host': 'app.onrender.com', 'X-App-Token': main.TOKEN, 'Content-Length': str(len(raw))}
        with patch.multiple('main', ALLOWED_HOST='app.onrender.com', PUBLIC=True), patch('main.PUBLIC_LIMITS', PublicRequestLimits()):
            for headers in [{**base, 'Origin': 'http://app.onrender.com'},
                            {**base, 'Origin': 'https://app.onrender.com', 'X-App-Token': 'wrong'}]:
                h = handler(headers, '/api/analyze-and-match', raw)
                h.do_POST()
                self.assertEqual(h.sent[0][0], 403)
            h = handler({**base, 'Origin': 'https://app.onrender.com'}, '/api/analyze-and-match', raw)
            h.do_POST()
            self.assertEqual(h.sent[0][0], 400)

    def test_public_blocks_override_registration(self):
        with patch('main.PUBLIC', True), self.assertRaises(ServiceError):
            main.dispatch_post('/api/register-product-override', {})

    def test_public_starts_with_or_without_old_password_setting(self):
        for old_password in ['', 'old-password']:
            conf = {'RENDER_EXTERNAL_HOSTNAME': 'app.onrender.com', 'PORT': '10000', 'APP_PASSWORD': old_password}
            with patch.multiple('main', PUBLIC=False, ALLOWED_HOST=''), patch('main.settings', return_value=conf), \
                    patch('sys.argv', ['main.py']), patch('main.LocalHTTPServer') as server:
                main.run()
                self.assertTrue(main.PUBLIC)
                server.assert_called_once_with(('0.0.0.0', 10000), main.Handler)
                server.return_value.serve_forever.assert_called_once()


if __name__ == '__main__':
    unittest.main()
