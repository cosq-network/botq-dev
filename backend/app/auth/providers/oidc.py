from ...errors import AuthenticationError
from ...extensions import db
from ...models import User
from ...orgs.service import ensure_roles, roles_for_org
from ...utils import new_uuid


class OIDCProvider:
    name = "oidc"

    def __init__(self, app):
        self.app = app
        self._oauth = None

    def _client(self):
        if self._oauth is None:
            from authlib.integrations.flask_client import OAuth

            oauth = OAuth(self.app)
            oauth.register(
                name="oidc",
                server_metadata_url=self.app.config["OIDC_ISSUER"]
                + "/.well-known/openid-configuration",
                client_id=self.app.config["OIDC_CLIENT_ID"],
                client_secret=self.app.config["OIDC_CLIENT_SECRET"],
                client_kwargs={"scope": self.app.config["OIDC_SCOPES"]},
            )
            self._oauth = oauth
        return self._oauth.oidc

    def authorization_url(self, redirect_uri: str, *, nonce: str):
        client = self._client()
        return client.authorize_redirect(redirect_uri=redirect_uri, nonce=nonce)

    def authenticate(self, code: str, redirect_uri: str, org_id, *, nonce: str) -> User:
        client = self._client()
        token = client.authorize_access_token(redirect_uri=redirect_uri)
        claims = client.parse_id_token(token, nonce=nonce)
        sub = str(claims.get("sub") or "").strip()
        email = (claims.get("email") or "").lower().strip()
        identity = sub or email
        if not identity:
            raise AuthenticationError("OIDC token missing subject identifier")
        if claims.get("email_verified") is False:
            raise AuthenticationError("OIDC email is not verified")
        org = self._org(org_id)
        user = User.query.filter_by(
            organization_id=org.id, external_provider="oidc", external_sub=identity
        ).first()
        if user is None and email:
            user = User.query.filter_by(organization_id=org.id, email=email).first()
        if user is not None:
            if not user.is_active:
                raise AuthenticationError("User is not active")
            user.external_provider = "oidc"
            user.external_sub = identity
            db.session.commit()
            return user
        ensure_roles(org)
        role_by_name = roles_for_org(org_id)
        user = User(
            id=new_uuid(),
            organization_id=org_id,
            email=email or f"{identity[:60]}@oidc.local",
            display_name=claims.get("name") or email or identity,
            external_provider="oidc",
            external_sub=identity,
        )
        db.session.add(user)
        db.session.flush()
        dev_role = role_by_name.get("developer")
        if dev_role:
            user.roles.append(dev_role)
        db.session.commit()
        return user

    def _org(self, org_id):
        from ...models import Organization

        org = Organization.query.get(org_id)
        if org is None or not org.is_active:
            raise AuthenticationError("Unknown organization")
        return org
