"""Offline routing regressions: actual GET races, cache and single-writer downloads."""
import io
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'OMGLite' / 'src'))
from omg.core import download as d

URL = 'https://api.github.com/repos/example/project/releases/latest'
FILE = 'https://github.com/example/project/releases/download/v1/file.zip'


class Response(io.BytesIO):
    def __init__(self, body=b'{"ok": true}', status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = {'Content-Length': str(len(body)), **(headers or {})}


class Opener:
    def __init__(self, fn):
        self.fn = fn
        self.calls = []

    def open(self, req, timeout):
        self.calls.append(req)
        return self.fn(req)


class RoutingTest(unittest.TestCase):
    def setUp(self):
        d.reset_route_cache()
        self.proxies = patch.object(d, 'get_system_proxies', return_value={})
        self.proxies.start()
        self.addCleanup(self.proxies.stop)
        self.delay = patch.object(d, 'FALLBACK_DELAY', .02)
        self.delay.start()
        self.addCleanup(self.delay.stop)
        self.mirrors = patch.object(d, 'GITHUB_PROXIES', ['https://mirror.test/'])
        self.mirrors.start()
        self.addCleanup(self.mirrors.stop)

    def use(self, fn):
        opener = Opener(fn)
        p = patch.object(d, 'get_openers', return_value=[('系统代理/SSL', opener)])
        p.start()
        self.addCleanup(p.stop)
        return opener

    def test_fast_original_does_not_start_mirror_or_probe(self):
        opener = self.use(lambda req: Response())
        self.assertEqual(d.fetch_json_api_smart(URL), {'ok': True})
        self.assertEqual([r.full_url for r in opener.calls], [URL])
        self.assertEqual(opener.calls[0].get_method(), 'GET')

    def test_slow_original_loses_and_late_response_closes(self):
        release = threading.Event()
        late = Response()
        def request(req):
            if req.full_url == URL:
                release.wait(2)
                return late
            return Response()
        opener = self.use(request)
        started = time.monotonic()
        self.assertEqual(d.fetch_json_api_smart(URL), {'ok': True})
        self.assertLess(time.monotonic() - started, .5)
        self.assertEqual(len(opener.calls), 2)
        release.set()
        for _ in range(100):
            if late.closed:
                break
            time.sleep(.005)
        self.assertTrue(late.closed)
        opener.calls.clear()
        d.fetch_json_api_smart(URL.replace('latest', 'tags/v2'))
        self.assertTrue(opener.calls[0].full_url.startswith('https://mirror.test/'))

    def test_invalid_json_is_not_success(self):
        self.use(lambda req: Response(b'<html>bad</html>' if req.full_url == URL else b'{"ok": true}'))
        self.assertEqual(d.fetch_json_api_smart(URL), {'ok': True})

    def test_failed_cached_route_falls_back_and_is_replaced(self):
        key, routes = d._routes(URL, True)
        d._remember(key, routes[1])
        def request(req):
            if req.full_url.startswith('https://mirror.test/'):
                raise OSError('offline')
            return Response()
        opener = self.use(request)
        self.assertEqual(d.fetch_json_api_smart(URL), {'ok': True})
        self.assertTrue(opener.calls[0].full_url.startswith('https://mirror.test/'))
        self.assertEqual(d._route_cache[key][0][0], '')

    def test_expired_and_network_specific_cache(self):
        self.use(lambda req: Response())
        key, routes = d._routes(URL, True)
        d._remember(key, routes[1])
        self.assertTrue(d._routes(URL, True)[1][0][0])
        with patch.object(d, 'ROUTE_CACHE_TTL', -1):
            self.assertEqual(d._routes(URL, True)[1][0][0], '')
        d._remember(key, routes[1])
        with patch.object(d, 'get_system_proxies', return_value={'https': 'http://localhost:1'}):
            self.assertNotEqual(key, d._cache_key(URL, True))
        self.assertNotEqual(key, d._cache_key(FILE, True))
        d.reset_youtube_cache()
        self.assertFalse(d._route_cache)

    def test_rate_limit_stops_without_mirror(self):
        def request(req):
            raise urllib.error.HTTPError(req.full_url, 403, 'Forbidden',
                                          {'X-RateLimit-Remaining': '0'}, io.BytesIO())
        opener = self.use(request)
        with self.assertRaises(d.RateLimitedError):
            d.fetch_json_api_smart(URL)
        self.assertEqual(len(opener.calls), 1)

    def test_disabled_mirrors_and_non_github(self):
        opener = self.use(lambda req: Response())
        d.fetch_url_smart(URL, use_proxies=False)
        d.fetch_url_smart('https://example.test/github.com')
        self.assertEqual(len(opener.calls), 2)
        self.assertFalse(d.is_github_url('https://github.com.evil.test/a'))
        self.assertTrue(d.is_github_url('https://raw.githubusercontent.com/a/b'))

    def test_cancel_before_request(self):
        opener = self.use(lambda req: Response())
        self.assertIsNone(d.fetch_url_smart(URL, should_cancel=lambda: True))
        self.assertEqual(opener.calls, [])

    def test_cancel_in_flight_returns_promptly(self):
        release = threading.Event()
        cancelled = threading.Event()
        def request(req):
            cancelled.set()
            release.wait(1)
            return Response()
        self.use(request)
        started = time.monotonic()
        try:
            self.assertIsNone(d.fetch_url_smart(URL, should_cancel=cancelled.is_set))
            self.assertLess(time.monotonic() - started, .3)
        finally:
            release.set()

    def test_download_single_writer_and_late_response_closed(self):
        release = threading.Event()
        late = Response(b'wrong')
        def request(req):
            if req.full_url == FILE:
                release.wait(1)
                return late
            return Response(b'correct')
        self.use(request)
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'file.zip'
            self.assertEqual(d.download_file_smart(FILE, str(dest)), (True, ''))
            release.set()
            for _ in range(100):
                if late.closed:
                    break
                time.sleep(.005)
            self.assertTrue(late.closed)
            self.assertEqual(dest.read_bytes(), b'correct')

    def test_resume_is_actual_get_without_probe(self):
        opener = self.use(lambda req: Response(b'def', 206, {'Content-Range': 'bytes 3-5/6'}))
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'file.zip'
            dest.write_bytes(b'abc')
            self.assertEqual(d.download_file_smart(FILE, str(dest)), (True, ''))
            self.assertEqual(dest.read_bytes(), b'abcdef')
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(opener.calls[0].get_header('Range'), 'bytes=3-')

    def test_ignored_range_overwrites(self):
        self.use(lambda req: Response(b'abcdef'))
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'file.zip'
            dest.write_bytes(b'abc')
            self.assertTrue(d.download_file_smart(FILE, str(dest))[0])
            self.assertEqual(dest.read_bytes(), b'abcdef')

    def test_invalid_range_and_html_fall_back(self):
        for bad in (lambda: Response(b'bad', 206, {'Content-Range': 'bytes 0-2/3'}),
                    lambda: Response(b'<html>error</html>', headers={'Content-Type': 'text/html'})):
            d.reset_route_cache()
            opener = self.use(lambda req: bad() if req.full_url == FILE else
                              Response(b'def', 206, {'Content-Range': 'bytes 3-5/6'}))
            with tempfile.TemporaryDirectory() as temp:
                dest = Path(temp) / 'file.zip'
                dest.write_bytes(b'abc')
                self.assertTrue(d.download_file_smart(FILE, str(dest))[0])
                self.assertEqual(dest.read_bytes(), b'abcdef')
            self.assertEqual(len(opener.calls), 2)

    def test_download_cancel_does_not_write(self):
        self.use(lambda req: Response(b'abc'))
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'file.zip'
            self.assertEqual(d.download_file_smart(FILE, str(dest), should_cancel=lambda: True),
                             (False, '已取消'))
            self.assertFalse(dest.exists())

    def test_interrupted_body_resumes_on_fallback(self):
        class Interrupted(Response):
            def read1(self, size):
                return io.BytesIO.read(self, 3)

            def read(self, size=-1):
                raise OSError('connection reset')

        def request(req):
            if req.full_url == FILE:
                return Interrupted(b'abcdef')
            self.assertEqual(req.get_header('Range'), 'bytes=3-')
            return Response(b'def', 206, {'Content-Range': 'bytes 3-5/6'})
        self.use(request)
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'file.zip'
            self.assertTrue(d.download_file_smart(FILE, str(dest))[0])
            self.assertEqual(dest.read_bytes(), b'abcdef')

    def test_known_length_finishes_without_an_extra_eof_read(self):
        class NoEOF(Response):
            def read(self, size=-1):
                raise AssertionError('Should not wait for EOF after Content-Length')
            def read1(self, size):
                return io.BytesIO.read(self, size)
        self.use(lambda req: NoEOF(b'abc', headers={'Content-Length': '3'}))
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'file.zip'
            self.assertTrue(d.download_file_smart(FILE, str(dest))[0])
            self.assertEqual(dest.read_bytes(), b'abc')

    def test_416_requires_confirmed_length(self):
        def request(req):
            raise urllib.error.HTTPError(req.full_url, 416, 'Range Not Satisfiable',
                                          {'Content-Range': 'bytes */3'}, io.BytesIO())
        self.use(request)
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / 'file.zip'
            dest.write_bytes(b'abc')
            self.assertTrue(d.download_file_smart(FILE, str(dest))[0])
            self.assertEqual(dest.read_bytes(), b'abc')
            dest.write_bytes(b'ab')
            with patch.object(d, 'MAX_RETRIES_PER_URL', 0):
                self.assertFalse(d.download_file_smart(FILE, str(dest))[0])
            self.assertEqual(dest.read_bytes(), b'ab')

    def test_worker_count_is_bounded(self):
        release = threading.Event()
        guard = threading.Lock()
        counts = {'active': 0, 'peak': 0}
        def operation(route):
            with guard:
                counts['active'] += 1
                counts['peak'] = max(counts['peak'], counts['active'])
            release.wait(.2)
            with guard:
                counts['active'] -= 1
            raise OSError('offline')
        with patch.object(d, 'FALLBACK_DELAY', .001):
            with self.assertRaises(OSError):
                d._race(URL, [(str(i), '', None) for i in range(7)], operation, ('test',))
        self.assertEqual(counts['peak'], d.MAX_ROUTE_WORKERS)

    def test_original_system_proxy_and_direct_are_distinct_routes(self):
        system = Opener(lambda req: Response())
        direct = Opener(lambda req: Response())
        with patch.object(d, 'get_system_proxies', return_value={'https': 'http://localhost:1'}), patch.object(
                d, 'get_openers', return_value=[('系统代理/SSL', system), ('直连/SSL', direct)]):
            _, routes = d._routes(FILE, True)
            self.assertEqual([(r[0], r[1]) for r in routes[:3]], [
                ('', '系统代理/SSL'), ('https://mirror.test/', '系统代理/SSL'), ('', '直连/SSL')])

    def test_real_http_download_redirect_and_resume(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        payload = b'actual download bytes'
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/file')
                    self.end_headers()
                    return
                start = int(self.headers.get('Range', 'bytes=0-')[6:-1])
                self.send_response(206 if start else 200)
                self.send_header('Content-Length', str(len(payload) - start))
                if start:
                    self.send_header('Content-Range', f'bytes {start}-{len(payload)-1}/{len(payload)}')
                self.end_headers()
                self.wfile.write(payload[start:])
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            opener = d.urllib.request.build_opener(d.urllib.request.ProxyHandler({}))
            with patch.object(d, 'get_openers', return_value=[('直连/SSL', opener)]):
                with tempfile.TemporaryDirectory() as temp:
                    dest = Path(temp) / 'file.zip'
                    dest.write_bytes(payload[:5])
                    url = f'http://127.0.0.1:{server.server_port}/redirect'
                    self.assertTrue(d.download_file_smart(url, str(dest))[0])
                    self.assertEqual(dest.read_bytes(), payload)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == '__main__':
    unittest.main()
