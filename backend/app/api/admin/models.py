from fastapi import APIRouter, Request

from app.api.admin.config import Session
from app.schemas.managed_model import (
    ConnectionVerifyInput,
    ConnectionVerifyResult,
    ExistingConnectionVerifyInput,
    ManagedModelCreate,
    ManagedModelList,
    ManagedModelUpdate,
    ManagedModelView,
    ModelServiceTestInput,
    ModelServiceTestResult,
)
from app.security.credentials import CredentialCipher
from app.services import managed_model_service as service

router = APIRouter(prefix="/models")


def _cipher(request: Request) -> CredentialCipher:
    return request.app.state.credential_cipher


@router.get("", response_model=ManagedModelList)
async def list_models(session: Session):
    return await service.list_models(session)


@router.post("", status_code=201, response_model=ManagedModelView)
async def create_model(body: ManagedModelCreate, request: Request, session: Session):
    return await service.create_model(session, body, _cipher(request))


@router.post("/verify", response_model=ConnectionVerifyResult)
async def verify_new_connection(body: ConnectionVerifyInput):
    return await service.verify_connection(
        body.base_url,
        body.api_key.get_secret_value(),
        body.timeout_seconds,
        model_name=body.model_name,
        temperature=body.temperature,
        top_p=body.top_p,
    )


@router.get("/{model_uid}", response_model=ManagedModelView)
async def get_model(model_uid: str, session: Session):
    return await service.get_model(session, model_uid)


@router.patch("/{model_uid}", response_model=ManagedModelView)
async def update_model(
    model_uid: str,
    body: ManagedModelUpdate,
    request: Request,
    session: Session,
):
    return await service.update_model(session, model_uid, body, _cipher(request))


@router.post("/{model_uid}/verify", response_model=ConnectionVerifyResult)
async def verify_existing_connection(
    model_uid: str,
    body: ExistingConnectionVerifyInput,
    request: Request,
    session: Session,
):
    replacement = body.api_key.get_secret_value() if body.api_key is not None else None
    return await service.verify_existing(
        session,
        model_uid,
        _cipher(request),
        replacement,
    )


@router.post("/{model_uid}/service-test", response_model=ModelServiceTestResult)
async def test_model_service(
    model_uid: str,
    body: ModelServiceTestInput,
    request: Request,
    session: Session,
):
    return await service.test_model_service(
        session,
        model_uid,
        body,
        _cipher(request),
    )


@router.post("/{model_uid}/default", response_model=ManagedModelView)
async def set_default_model(model_uid: str, session: Session):
    return await service.set_default(session, model_uid)


@router.post("/{model_uid}/enable", response_model=ManagedModelView)
async def enable_model(model_uid: str, session: Session):
    return await service.set_enabled(session, model_uid, enabled=True)


@router.post("/{model_uid}/disable", response_model=ManagedModelView)
async def disable_model(model_uid: str, session: Session):
    return await service.set_enabled(session, model_uid, enabled=False)
