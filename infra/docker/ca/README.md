# Extra CA certificates for image builds

Behind a TLS-inspecting corporate proxy, drop the proxy's root certificate here as `*.crt` before building.
Both images install it into the system trust store and point pip, uv, npm and Node at it. Certificates are
git-ignored; this folder ships empty. Pass `HTTPS_PROXY`/`HTTP_PROXY` as build arguments if a proxy is required.
