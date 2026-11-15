# Keycloak setup for AgriVerse development

This guide connects an existing Keycloak realm to AgriVerse staff sign-in.
It uses the `agriverse` realm, the `agriverse-web` client, and the following
development addresses:

| Component | Address |
|---|---|
| AgriVerse web | `http://localhost:3001` |
| AgriVerse API | `http://localhost:8000` |
| Keycloak example | `https://wisdom-dev.local/keycloak` |

The Keycloak address reflects the deployment shown during setup. Confirm its
HTTP/HTTPS scheme using discovery in step 4. Preserve the `/keycloak` prefix
when your server uses it. For another deployment, substitute its actual base URL.

## 1. Select the realm and create a client

Select **agriverse** in the Keycloak Admin Console. If the realm does not exist,
create it first. Use the application realm rather than the `master` realm.

Open **Clients → Create client** and enter:

| Field | Value |
|---|---|
| Client type | `OpenID Connect` |
| Client ID | `agriverse-web` |
| Name | `AgriVerse` (optional) |

Continue to **Capability config**:

| Setting | Development value |
|---|---|
| Client authentication | **Off** |
| Authorization | **Off** |
| Standard flow | **On** |
| Direct access grants | **Off** |
| Other authentication flows | **Off** |

Set **PKCE Code Challenge Method** to **S256**. Depending on the Keycloak
version, this appears in the creation wizard or under the saved client's
**Advanced** settings. AgriVerse sends S256 PKCE for this flow.

This creates a public development client, so its application configuration will
have a blank client secret. For a confidential client instead, enable client
authentication and put its generated secret from **Credentials** into
`KEYCLOAK_CLIENT_SECRET`.

## 2. Configure login URLs

On **Login settings**, enter:

| Field | Value |
|---|---|
| Root URL | `http://localhost:3001` |
| Home URL | `http://localhost:3001` |
| Valid redirect URIs | `http://localhost:8000/api/v1/auth/staff/oauth/keycloak/callback` |
| Web origins | `http://localhost:3001` |

Click **Save**. Keep the `email` and `profile` client scopes available.

The registered Keycloak redirect goes to the **API on port 8000**. After the
API completes authentication, it redirects to the web application's separate
callback at `http://localhost:3001/api/oauth/callback`. These URLs serve different
steps and must match the application's configuration.

## 3. Create a Keycloak user

Open **Users → Add user** in the `agriverse` realm:

1. Enter a username and the required first/last name fields.
2. Set **Email** to the same address as AgriVerse's `BOOTSTRAP_EMAIL` for the
   first organization administrator.
3. For a development user you administer, set **Email verified → On**, or
   complete Keycloak's email verification flow.
4. Save the user, then open **Credentials → Set password**.
5. Set a password and turn **Temporary → Off** for this development account.

Use that user's credentials on Keycloak's login screen. AgriVerse's bootstrap
PIN remains a separate login method available in development and production
when `STAFF_PIN_LOGIN_ENABLED=true` (the default).

The bootstrap administrator must already exist in AgriVerse. If it has not been
created, configure `BOOTSTRAP_NAME`, `BOOTSTRAP_PHONE`, `BOOTSTRAP_PIN`, and
`BOOTSTRAP_EMAIL` in root `.env`, then run once on an empty application database:

```powershell
uv run --project apps/api python -m agriverse.cli bootstrap
```

Save the organization UUID printed by bootstrap. Changing `BOOTSTRAP_EMAIL`
afterward does not update an existing database account.

Other new staff need an email-bound AgriVerse invitation. Keycloak realm/client
roles do not automatically create application membership or grant `org_admin`.

## 4. Obtain the exact issuer URL

In **Realm settings**, open **Endpoints → OpenID Endpoint Configuration**.
Copy the JSON document's **`issuer`** value exactly, including its scheme and
any deployment prefix.

For the example server, discovery is expected at:

```text
https://wisdom-dev.local/keycloak/realms/agriverse/.well-known/openid-configuration
```

An example issuer is:

```text
https://wisdom-dev.local/keycloak/realms/agriverse
```

Use HTTPS if the discovery document advertises HTTPS. Do not use the admin
console URL or append `/.well-known/openid-configuration` to the issuer setting.
The API and the user's browser must both resolve and reach the advertised host.

## 5. Configure AgriVerse

Update the repository root `.env`. The example below assumes discovery reports
the HTTP issuer shown above; replace it with your exact discovered issuer:

```dotenv
KEYCLOAK_ISSUER_URL=https://wisdom-dev.local/keycloak/realms/agriverse
KEYCLOAK_CLIENT_ID=agriverse-web
KEYCLOAK_CLIENT_SECRET=

WEB_ORIGIN=http://localhost:3001
CORS_ORIGINS=["http://localhost:3001"]
OAUTH_CALLBACK_BASE_URL=http://localhost:8000/api/v1
WEB_OAUTH_CALLBACK_URL=http://localhost:3001/api/oauth/callback
```

Leave `KEYCLOAK_CLIENT_SECRET` empty when **Client authentication** is **Off**.
For a confidential client, provide its actual secret privately in `.env`.

Both the API and web scripts load root `.env`. Existing process environment
variables take precedence, so remove stale shell overrides if settings appear
unchanged. Restart both servers after configuration changes.

## 6. Start and verify sign-in

From the repository root, start the API and web in separate terminals:

```powershell
uv run --project apps/api uvicorn agriverse.main:app --app-dir apps/api --reload --reload-dir apps/api/agriverse --port 8000
```

```powershell
corepack pnpm dev
```

Open `http://localhost:3001/login`, enter the organization UUID printed during
bootstrap, and select **Continue with Keycloak**. Sign in with the user created
in step 3. The application should return you to the staff review console for an
organization administrator.

AgriVerse uses OIDC discovery, token/state/nonce verification, PKCE, verified
email, and issuer/subject binding. Existing organization membership and invitation
checks still apply. The first live login verifies your realm configuration;
automated application tests use mocked OIDC responses.

## Troubleshooting

| Symptom | Check |
|---|---|
| Keycloak button is missing | Both `KEYCLOAK_ISSUER_URL` and `KEYCLOAK_CLIENT_ID` must be set; restart the web server |
| OAuth provider is not configured | Check the API's environment and restart the API |
| Invalid redirect URI | Register the exact port-8000 callback from step 2; match hostname, scheme, path, and trailing slash |
| Email is not verified | Verify the Keycloak user's email and ensure the `email` scope is available |
| Staff invitation required or membership unavailable | Match the existing bootstrap account's email and organization UUID, or use an appropriate staff invitation |
| Account is linked to a different identity | Use the originally linked identity; changing the trusted realm does not automatically relink an account |
| Discovery, issuer, or token request fails | Check DNS, reachability, the `/keycloak` prefix, and the exact issuer advertised in discovery |

Use public HTTPS origins and corresponding callback URLs for production. OIDC
is optional there too: accounts with a registered phone and PIN can use staff
PIN login. Set `STAFF_PIN_LOGIN_ENABLED=false` in both the API and web environments
to require a configured OIDC provider for staff access instead. This flag does
not provision phone/PIN credentials for existing OIDC-only accounts.

## References

- [Keycloak client configuration](https://www.keycloak.org/docs/latest/server_admin/index.html#_oidc_clients)
- [Keycloak OIDC discovery and endpoints](https://www.keycloak.org/securing-apps/oidc-layers)
- [AgriVerse AI provider setup](AI_AND_KEYCLOAK_SETUP.md)
