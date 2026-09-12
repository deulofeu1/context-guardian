# Publishing

Context Guardian publishes its npm packages through npm Trusted Publishing and
GitHub Actions OIDC. No long-lived `NPM_TOKEN` is required.

## npm packages

The repository publishes:

- `@context-guardian/pi`
- `context-guardian-deepseek-harness`

The GitHub Actions workflow is `.github/workflows/release.yml`. In each npm
package's settings, add a GitHub Actions trusted publisher with:

- Organization or user: `deulofeu1`
- Repository: `context-guardian`
- Workflow filename: `release.yml`
- Environment name: leave empty
- Allowed action: direct `npm publish`

The package metadata contains the public repository URL required by npm provenance.
Trusted publishing also produces provenance automatically when publishing from this
public GitHub repository.

## First publication

npm's trusted-publisher relationship is configured on an existing package. For the
first `0.1.0` publication, sign in locally with npm and publish interactively with
your account's normal 2FA challenge; this does not create an automation token:

```bash
npm login
cd adapters/pi
npm publish --access public

cd ../deepseek-harness
npm publish --access public
```

After both package pages exist, configure their trusted publishers and do not add an
`NPM_TOKEN` secret.

## Subsequent releases

1. Bump the version in the package that changed.
2. Push the commit to `main`.
3. Open GitHub Actions → `Publish packages` → `Run workflow`.
4. Select `npm` or `all`.

The npm job installs npm 11.5.1+, requests the GitHub OIDC identity token, runs the
checks, and publishes both packages without a registry token. `npm whoami` is not a
valid Trusted Publishing check because OIDC authentication exists only during the
publish operation.

For stricter release review, configure the trusted publisher for staged publishing
and change the workflow to `npm stage publish`; approval then happens separately
with 2FA.
