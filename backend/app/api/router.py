from fastapi import APIRouter

from app.api.v1 import (
    analytics,
    audit,
    auth,
    chat,
    curation,
    departments,
    directory,
    directory_admin,
    documents,
    evaluation,
    groups,
    guides,
    indexing,
    knowledge_bases,
    models_admin,
    notifications,
    open_admin,
    open_api,
    organizations,
    retrieval_admin,
    roles,
    search,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(departments.router)
api_router.include_router(users.router)
api_router.include_router(groups.router)
api_router.include_router(roles.router)
api_router.include_router(audit.router)
api_router.include_router(knowledge_bases.router)
api_router.include_router(documents.router)
api_router.include_router(directory.router)
api_router.include_router(directory_admin.router)
api_router.include_router(indexing.router)
api_router.include_router(search.router)
api_router.include_router(retrieval_admin.router)
api_router.include_router(chat.router)
api_router.include_router(curation.router)
api_router.include_router(notifications.router)
api_router.include_router(guides.router)
api_router.include_router(analytics.router)
api_router.include_router(evaluation.router)
api_router.include_router(models_admin.router)
api_router.include_router(open_admin.router)
api_router.include_router(open_api.router)
