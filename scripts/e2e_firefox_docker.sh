#!/usr/bin/env bash
# Run the Firefox browser project locally in Playwright's Linux image (ENV-P8-01): Playwright's Firefox build does not
# start on macOS 27 ("Could not find profile folder"), so this runs the same engine CI uses, against the LOCAL stack.
#
# Needs: Docker (or Colima) and the local disposable stack on :3100 / :8000 (see STATUS.md). Inside the container a
# small TCP relay makes 127.0.0.1:3100 reach the host's web server, so the suite's disposable-stack guard (D-065,
# e2e/disposable.ts) still sees a loopback URL and still checks that the API says the stack is disposable. Do not point
# it at any other stack.
#
#   scripts/e2e_firefox_docker.sh            # the firefox project
#   scripts/e2e_firefox_docker.sh -g "J12"   # extra Playwright arguments are passed through
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PW_VERSION="$(node -p "require('$ROOT/apps/web/node_modules/@playwright/test/package.json').version")"
curl -fsS http://localhost:3100/api/v1/auth/config | grep -q '"disposable":true' \
  || { echo "the local stack on :3100 is not running or not disposable" >&2; exit 1; }
exec docker run --rm --ipc=host --add-host=host.docker.internal:host-gateway \
  -v "$ROOT":/work -w /work/apps/web \
  -e SUPPLYLENS_E2E_ALLOW_DESTRUCTIVE="${SUPPLYLENS_E2E_ALLOW_DESTRUCTIVE:-1}" -e E2E_JSON=/tmp/e2e-firefox.json \
  "mcr.microsoft.com/playwright:v${PW_VERSION}-noble" \
  bash -c 'node -e "const n=require(\"net\");n.createServer(c=>{const s=n.connect(3100,\"host.docker.internal\");c.pipe(s);s.pipe(c);s.on(\"error\",()=>c.destroy());c.on(\"error\",()=>s.destroy())}).listen(3100,\"127.0.0.1\")" & sleep 1; exec npx playwright test --project firefox --reporter=line --output /tmp/test-results-firefox "$@"' _ "$@"
