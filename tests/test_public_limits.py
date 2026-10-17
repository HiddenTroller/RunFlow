import io
import json
import unittest
from unittest.mock import Mock, patch

import main
from public_limits import PublicRequestLimits, RateLimitError


class PublicLimitTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.limits = PublicRequestLimits(api_limit=2, photo_limit=2, max_active_photos=1, clock=lambda: self.now)

    def test_rolling_api_window_and_retry(self):
        self.limits.api_request()
        self.limits.api_request()
        with self.assertRaises(RateLimitError) as caught:
            self.limits.api_request()
        self.assertEqual(caught.exception.retry_after, 60)
        self.now += 60
        self.limits.api_request()

    def test_concurrency_release_does_not_erase_attempts(self):
        with self.limits.analysis():
            with self.assertRaises(RateLimitError):
                with self.limits.analysis():
                    self.fail('concurrent request admitted')
        with self.assertRaises(ValueError):
            with self.limits.analysis():
                raise ValueError('upstream failure')
        with self.assertRaises(RateLimitError):
            with self.limits.analysis():
                self.fail('failed analysis must still count')
        self.now += 600
        with self.limits.analysis():
            pass

    def test_photo_routes_share_budget_and_local_bypasses_it(self):
        data = {'consent': True, 'base64': 'eA==', 'mime': 'image/png'}
        with patch.multiple('main', PUBLIC=True, PUBLIC_LIMITS=self.limits), \
                patch('main.analyze_photo', return_value={}) as studio, \
                patch.object(main.WORKFLOW, 'analyze_and_match', return_value={}) as flow:
            main.dispatch_post('/api/studio', data)
            main.dispatch_post('/api/analyze-and-match', data)
            with self.assertRaises(RateLimitError):
                main.dispatch_post('/api/studio', data)
            studio.assert_called_once()
            flow.assert_called_once()
        with patch.multiple('main', PUBLIC=False, PUBLIC_LIMITS=self.limits), patch('main.analyze_photo', return_value={}):
            main.dispatch_post('/api/studio', data)

    def test_limit_returns_429_without_dispatching_upstream(self):
        raw = json.dumps({}).encode()
        h = object.__new__(main.Handler)
        h.headers = {'Host': 'app.onrender.com', 'Origin': 'https://app.onrender.com',
                     'X-App-Token': main.TOKEN, 'Content-Length': str(len(raw))}
        h.path, h.rfile = '/api/search', io.BytesIO(raw)
        h.send = Mock()
        self.limits.api_request()
        self.limits.api_request()
        with patch.multiple('main', PUBLIC=True, PUBLIC_LIMITS=self.limits, ALLOWED_HOST='app.onrender.com'), \
                patch('main.dispatch_post') as dispatch:
            h.do_POST()
            self.assertEqual(h.send.call_args.args[0], 429)
            self.assertEqual(h.send.call_args.args[3], 60)
            dispatch.assert_not_called()

    def test_retry_after_header_is_sent(self):
        h = object.__new__(main.Handler)
        h.send_response, h.end_headers = Mock(), Mock()
        h.wfile, headers = io.BytesIO(), {}
        h.send_header = lambda key, value: headers.update({key: value})
        h.send(429, {'error': 'wait'}, retry_after=7)
        self.assertEqual(headers['Retry-After'], '7')


if __name__ == '__main__':
    unittest.main()
