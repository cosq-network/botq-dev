from werkzeug.security import check_password_hash, generate_password_hash

from ...extensions import db
from ...models import Role, User
from ...orgs.service import ensure_roles
from ...utils import new_uuid


class LocalProvider:
    name = "local"

    def __init__(self, org_slug: str):
        self.org_slug = org_slug

    def authenticate(self, email: str, password: str) -> User | None:
        org = self._find_org()
        if org is None:
            return None
        user = User.query.filter_by(organization_id=org.id, email=email.lower().strip()).first()
        if user is None or not user.password_hash:
            return None
        if not check_password_hash(user.password_hash, password):
            return None
        if not user.is_active:
            return None
        return user

    def ensure_local_user(
        self, email: str, password: str, display_name: str, role_names=None
    ) -> User:
        org = self._resolve_org()
        user = User.query.filter_by(organization_id=org.id, email=email.lower().strip()).first()
        if user is None:
            user = User(
                id=new_uuid(),
                organization_id=org.id,
                email=email.lower().strip(),
                display_name=display_name.strip(),
                password_hash=generate_password_hash(password),
            )
            db.session.add(user)
            db.session.flush()
        ensure_roles(org)
        role_by_name = {
            role.name: role for role in Role.query.filter_by(organization_id=org.id).all()
        }
        names = role_names or ["developer"]
        for name in names:
            role = role_by_name.get(name)
            if role and role not in user.roles:
                user.roles.append(role)
        db.session.commit()
        return user

    def _resolve_org(self):
        org = self._find_org()
        if org is None:
            raise RuntimeError(f"Organization '{self.org_slug}' does not exist")
        return org

    def _find_org(self):
        from ...models import Organization

        return Organization.query.filter_by(slug=self.org_slug, is_active=True).first()
