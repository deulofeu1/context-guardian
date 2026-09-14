# Publishing

Context Guardian publishes its npm packages through npm Trusted Publishing and
GitHub Actions OIDC. No long-lived `NPM_TOKEN` is required.

## npm packages

The repository publishes:

- `@context-guardian/pi`
- `context-guardian-deepseek-harness`

The npm account used for the first publication must own the
`@context-guardian` scope. If that scope is not already available, create the
`context-guardian` npm organization and grant the publishing account access, or
rename the Pi package to a scope that the account owns before publishing.

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

## First publication (historical)

npm's trusted-publisher relationship is configured on an existing package. The first
`0.1.0` publication was completed locally with npm 2FA; this did not create an
automation token:

```bash
npm login
cd adapters/pi
npm publish --access public

cd ../deepseek-harness
npm publish --access public
```

Both package pages now exist. Keep the trusted-publisher configuration on each
package and do not add an `NPM_TOKEN` secret.

## Subsequent releases

1. Bump the version in the package that changed.
2. Push the commit to `main`.
3. Open GitHub Actions → `Publish packages` → `Run workflow`.
4. Select the package set that has a new version: `python`, `pi`,
   `deepseek-harness`, `python-and-deepseek-harness`, or `all`.

Use `all` only when the Python core and both npm packages all have new versions.
Selecting `pi` or `deepseek-harness` publishes only that adapter, so a patch release
does not try to republish an existing version of the other npm package.

The `all` workflow publishes the Python package first and waits for it to succeed
before publishing npm packages. This prevents a new adapter protocol from becoming
available while the matching Python core is still unavailable. For a DeepSeek
Harness compatibility release, update and verify the Python core and adapter
together, then select `python-and-deepseek-harness`. Use `all` only when the Pi
package also has a new version. All combined options publish Python first and only
then publish the matching npm package(s).

The npm job installs npm 11.5.1+, requests the GitHub OIDC identity token, runs the
checks, and publishes the selected npm package(s) without a registry token.
`npm whoami` is not a valid Trusted Publishing check because OIDC authentication
exists only during the publish operation.

For stricter release review, configure the trusted publisher for staged publishing
and change the workflow to `npm stage publish`; approval then happens separately
with 2FA.
