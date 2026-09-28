# E2E tests

The Playwright suite targets a running production-style application. It does not
start or reset the server and never provisions a user.

```bash
npm --prefix e2e ci
npx --prefix e2e playwright install chromium
BASE_URL=http://127.0.0.1:8082 npm --prefix e2e test
```

Чтобы использовать уже установленный Google Chrome вместо скачанного Chromium,
добавьте `PLAYWRIGHT_CHANNEL=chrome`.

`BASE_URL` defaults to `http://127.0.0.1:8082`. The unauthenticated and narrow
login checks always run. To enable authenticated desktop and 360 px smoke tests,
provide credentials for an existing local owner:

```bash
E2E_USERNAME=owner E2E_PASSWORD='local password' npm --prefix e2e test
```

The credentials are read only from the process environment and are not persisted
by the suite. Each test receives an isolated browser context.
