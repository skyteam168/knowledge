"""Classification gates retrieval hydrate beyond mere read ACL."""

from app.services.authz.acl import AclPermission
from app.services.knowledge.document_effect import retrieval_min_acl


def test_retrieval_min_acl_matrix() -> None:
    assert retrieval_min_acl(None) is None
    assert retrieval_min_acl("internal") is None
    assert retrieval_min_acl("confidential") is None
    assert retrieval_min_acl("restricted") == AclPermission.EDIT.value
    assert retrieval_min_acl("secret") == AclPermission.MANAGE.value
