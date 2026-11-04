import socket, sys, threading, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skill' / 'scripts'))
import gf_evidence as ev

PUB = '93.184.216.34'


def resolver_for(*ips):
    return lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port)) for ip in ips]


def serve(responses, log):
    """Connector backed by socketpairs; responses maps request path -> raw bytes."""
    def connector(addr, timeout):
        log.append(addr)
        a, b = socket.socketpair()
        def run():
            data = b''
            while b'\r\n\r\n' not in data: data += b.recv(4096)
            path = data.split(b' ', 2)[1].decode()
            log.append(data)
            b.sendall(responses[path]); b.close()
        threading.Thread(target=run, daemon=True).start()
        return a
    return connector


def page(body=b'hello world', ctype='text/html; charset=utf-8', extra=''):
    return b'HTTP/1.1 200 OK\r\nContent-Type: ' + ctype.encode() + b'\r\n' + extra.encode() + b'Content-Length: %d\r\n\r\n' % len(body) + body


def redirect(loc):
    return b'HTTP/1.1 302 Found\r\nLocation: ' + loc.encode() + b'\r\nContent-Length: 0\r\n\r\n'


class FetcherTests(unittest.TestCase):
    def test_rebinding_connects_only_to_vetted_ip(self):
        calls = []
        def res(host, port, **kw):
            calls.append(1)
            return resolver_for(PUB if len(calls) == 1 else '127.0.0.1')(host, port)
        log = []
        out = ev.fetch_public('http://example.com/', res, serve({'/': page()}, log))
        self.assertEqual(out['text'], 'hello world')
        self.assertEqual([x for x in log if isinstance(x, tuple)], [(PUB, 80)])
        self.assertIn(b'Host: example.com\r\n', log[1])

    def test_check_public_url_shape(self):
        self.assertEqual(ev.check_public_url('https://Example.com:443/', resolver_for(PUB)), ('example.com', 443, 'https', PUB))
        self.assertEqual(ev.check_public_url('https://[2606:4700::1111]/', resolver_for('2606:4700::1111'))[3], '2606:4700::1111')
        with self.assertRaises(ValueError): ev.check_public_url('http://example.com/', resolver_for(PUB, '10.0.0.1'))

    def test_ports(self):
        with self.assertRaisesRegex(ValueError, 'Port 6379 not allowed'): ev.check_public_url('http://example.com:6379/', resolver_for(PUB))
        with self.assertRaisesRegex(ValueError, 'Port 443'): ev.check_public_url('http://example.com:443/', resolver_for(PUB))
        log = []
        with self.assertRaisesRegex(ValueError, 'Port 6379'):
            ev.fetch_public('http://example.com/', resolver_for(PUB), serve({'/': redirect('http://example.com:6379/')}, log))

    def test_charset_fallback_and_isolation(self):
        bad = page(b'caf\xc3\xa9 text', 'text/plain; charset=x-bogus')
        out = ev.fetch_public('http://example.com/', resolver_for(PUB), serve({'/': bad}, []))
        self.assertTrue(out['charset_fallback']); self.assertEqual(out['text'], 'café text')
        def fetcher(url):
            if 'bad' in url: return ev.fetch_public(url, resolver_for(PUB), serve({'/bad': bad}, []))
            if 'boom' in url: raise KeyError('x')
            return {'url': url, 'content_sha256': 'h', 'text': 'good quote here'}
        data = {'claims': [{'id': str(i), 'source_url': f'http://example.com/{n}', 'supporting_quote': 'good quote'}
                           for i, n in enumerate(['a', 'bad', 'boom', 'c', 'd'])]}
        rep = ev.analyze(data, allow_network=True, fetcher=fetcher)
        self.assertEqual(len(rep['claims']), 5)
        self.assertEqual([c['fetch_status'] for c in rep['claims']], ['fetched', 'fetched', 'failed', 'fetched', 'fetched'])
        self.assertTrue(rep['claims'][1]['charset_fallback'])

    def test_gzip_and_downgrade(self):
        with self.assertRaisesRegex(RuntimeError, 'content encoding'):
            ev.fetch_public('http://example.com/', resolver_for(PUB), serve({'/': page(extra='Content-Encoding: gzip\r\n')}, []))
        out = ev.fetch_public('https://example.com/', resolver_for(PUB), serve({'/': redirect('http://example.com/x'), '/x': page()}, []),
                              type('Ctx', (), {'wrap_socket': lambda self, sock, server_hostname: sock})())
        self.assertTrue(out['downgraded_to_http'])

    def test_wall_clock_budget_across_redirects(self):
        t = [0.0]
        def clock():  # each hop "takes" 9 s
            t[0] += 9
            return t[0]
        log, seen = [], []
        inner = serve({'/': redirect('/a'), '/a': redirect('/b'), '/b': page()}, log)
        def connector(addr, timeout):
            seen.append(timeout)
            return inner(addr, timeout)
        orig, ev._clock = ev._clock, clock
        try:
            with self.assertRaisesRegex(RuntimeError, 'Timed out after 20s'):
                ev.fetch_public('http://example.com/', resolver_for(PUB), connector)
        finally:
            ev._clock = orig
        self.assertEqual(len(seen), 2)  # third hop never connects
        self.assertTrue(all(x <= ev.TIMEOUT for x in seen))

    def test_first_address_down_tries_next(self):
        log = []
        inner = serve({'/': page()}, log)
        def connector(addr, timeout):
            if addr[0] == PUB: raise OSError('down')
            return inner(addr, timeout)
        out = ev.fetch_public('http://example.com/', resolver_for(PUB, '93.184.216.35'), connector)
        self.assertEqual(out['text'], 'hello world')

    def test_tls_hostname_mismatch_fails(self):
        import ssl, shutil, subprocess, tempfile, os
        if not shutil.which('openssl'): self.skipTest('openssl missing')
        try: srv = socket.socket(); srv.bind(('127.0.0.1', 0)); srv.listen(1)
        except OSError: self.skipTest('no loopback sockets')
        d = tempfile.mkdtemp()
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', f'{d}/k', '-out', f'{d}/c', '-days', '1',
                        '-subj', '/CN=other.example', '-addext', 'subjectAltName=DNS:other.example'], check=True, capture_output=True)
        sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); sctx.load_cert_chain(f'{d}/c', f'{d}/k')
        def run():
            try: sctx.wrap_socket(srv.accept()[0], server_side=True).recv(1)
            except (ssl.SSLError, OSError): pass
        threading.Thread(target=run, daemon=True).start()
        cctx = ssl.create_default_context(cafile=f'{d}/c')  # trusts the cert; name must still match
        port = srv.getsockname()[1]
        conn = ev.PinnedHTTPSConnection('example.com', port, ['127.0.0.1'], None, cctx, timeout=5)
        with self.assertRaises(ssl.SSLCertVerificationError): conn.connect()
        srv.close()


if __name__ == '__main__':
    unittest.main()
