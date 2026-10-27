"""인증된 사용자 자신에게만 동작하는 게임 API."""
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from game.schemas import (AccessoryIn, Character, CharacterNameIn, GameStateOut,
                          PurchaseResult, ShopItem, SyncOut, TitleIn)
from game.service import GameService
from server_auth import get_verified_user_id


router = APIRouter(prefix="/game", tags=["game"])
User = Annotated[str, Depends(get_verified_user_id)]


def get_service(request: Request) -> GameService:
    service = getattr(request.app.state, "game_service", None)
    if service is None:
        raise HTTPException(503, "게임 모듈이 아직 준비되지 않았습니다.")
    return service


Service = Annotated[GameService, Depends(get_service)]


def invoke(work):
    try:
        return work()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(503, "게임 데이터를 처리하지 못했습니다. 다시 시도해주세요.") from None


@router.post("/character", response_model=Character)
def create_character(body: CharacterNameIn, user: User, service: Service):
    return invoke(lambda: service.create_character(user, body.name))


@router.post("/character/name", response_model=Character)
def set_name(body: CharacterNameIn, user: User, service: Service):
    return invoke(lambda: service.set_character_name(user, body.name))


@router.get("/state", response_model=GameStateOut | None)
def get_state(user: User, service: Service):
    return invoke(lambda: service.get_game_state(user))


@router.post("/sync", response_model=SyncOut)
def sync(request: Request, user: User, service: Service):
    source = getattr(request.app.state, "game_event_source", None)
    if source is None:
        raise HTTPException(503, "학습 이벤트 연동이 아직 준비되지 않았습니다.")
    return invoke(lambda: service.sync_events(user, source))


@router.post("/title", response_model=GameStateOut)
def set_title(body: TitleIn, user: User, service: Service):
    return invoke(lambda: service.set_title(user, body.title_id))


@router.get("/shop", response_model=list[ShopItem])
def shop(user: User, service: Service):
    return invoke(lambda: service.list_shop_items(user))


@router.post("/accessories/purchase", response_model=PurchaseResult)
def purchase(body: AccessoryIn, user: User, service: Service,
             idempotency_key: Annotated[str, Header(min_length=1, max_length=200)]):
    return invoke(lambda: service.purchase_accessory(user, body.accessory_id, idempotency_key))


@router.post("/accessories/equip", response_model=GameStateOut)
def equip(body: AccessoryIn, user: User, service: Service):
    return invoke(lambda: service.equip_accessory(user, body.accessory_id))


@router.post("/accessories/unequip", response_model=GameStateOut)
def unequip(user: User, service: Service):
    return invoke(lambda: service.equip_accessory(user, None))
