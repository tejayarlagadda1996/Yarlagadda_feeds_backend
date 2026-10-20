from fastapi import APIRouter

from app.schemas.modules import ModuleInfo, ModulesResponse

router = APIRouter(prefix="/modules", tags=["modules"])

FACTORY_MODULES: list[ModuleInfo] = [
    ModuleInfo(
        id="raw_materials",
        title="Materials",
        description="Buy & stock",
        status="ready",
        icon="inventory",
    ),
    ModuleInfo(
        id="payments",
        title="Pay Vendor",
        description="Vendor dues & pay",
        status="ready",
        icon="payments",
    ),
    ModuleInfo(
        id="labour",
        title="Workers",
        description="Salary & advance",
        status="ready",
        icon="groups",
    ),
    ModuleInfo(
        id="fish_catch",
        title="Fish Sale",
        description="Catch & sell",
        status="ready",
        icon="set_meal",
    ),
]


@router.get("", response_model=ModulesResponse)
def list_modules() -> ModulesResponse:
    return ModulesResponse(modules=FACTORY_MODULES)
