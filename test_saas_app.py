import json
import os
import tempfile
import threading
import time
import unittest
from urllib import request

from saas_app import ControlPlane, SaaSAppHandler
from http.server import ThreadingHTTPServer


class SaaSAppTest(unittest.TestCase):
    def test_signup_login_and_tenant_flow(self):
        with tempfile.TemporaryDirectory() as td:
            cwd = os.getcwd()
            os.chdir(td)
            try:
                cp = ControlPlane(db_path='control.db', token_secret='x')
                cp.init()
                SaaSAppHandler.cp = cp
                server = ThreadingHTTPServer(('127.0.0.1', 0), SaaSAppHandler)
                port = server.server_port
                t = threading.Thread(target=server.serve_forever, daemon=True)
                t.start()

                def api(path, method='GET', body=None, token=None):
                    req = request.Request(f'http://127.0.0.1:{port}{path}', method=method)
                    req.add_header('Content-Type', 'application/json')
                    if token:
                        req.add_header('Authorization', f'Bearer {token}')
                    data = json.dumps(body).encode() if body is not None else None
                    with request.urlopen(req, data=data) as r:
                        return json.loads(r.read().decode())

                signup = api('/api/auth/signup', 'POST', {'org_name': 'Acme', 'email': 'a@a.com', 'password': 'pass123'})
                self.assertIn('org_id', signup)

                login = api('/api/auth/login', 'POST', {'email': 'a@a.com', 'password': 'pass123'})
                token = login['token']
                self.assertTrue(token)

                seed = api('/api/org/seed', 'POST', {'count': 1000}, token)
                self.assertGreater(seed['inserted'], 0)

                run = api('/api/org/run', 'POST', {'days': 10}, token)
                self.assertEqual(len(run['results']), 10)

                report = api('/api/org/report', 'GET', None, token)
                self.assertIn('outreaches', report)

                orgs = api('/api/admin/orgs', 'GET', None, token)
                self.assertGreaterEqual(len(orgs['organizations']), 1)

                server.shutdown()
                server.server_close()
                t.join(timeout=2)
            finally:
                os.chdir(cwd)


if __name__ == '__main__':
    unittest.main()
