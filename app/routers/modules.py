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
    ModuleInfo(
        id="feed_prep",
        title="Make Feed",
        description="Prepare feed",
        status="ready",
        icon="factory",
    ),
    ModuleInfo(
        id="expenses",
        title="Spending",
        description="Other costs",
        status="ready",
        icon="trending_down",
    ),
    ModuleInfo(
        id="income",
        title="Money In",
        description="Other income",
        status="ready",
        icon="trending_up",
    ),
    ModuleInfo(
        id="investments",
        title="Investment",
        description="Money put in",
        status="ready",
        icon="account_balance",
    ),
    ModuleInfo(
        id="reports",
        title="This Month",
        description="Month total",
        status="ready",
        icon="assessment",
    ),
]


@router.get("", response_model=ModulesResponse)
def list_modules() -> ModulesResponse:
    return ModulesResponse(modules=FACTORY_MODULES)
