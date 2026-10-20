from fastapi import APIRouter

from app.schemas.modules import ModuleInfo, ModulesResponse

router = APIRouter(prefix="/modules", tags=["modules"])

FACTORY_MODULES: list[ModuleInfo] = [
    ModuleInfo(
        id="raw_materials",
        title="Raw Materials",
        description="Buy materials, track stock, and manage inventory",
        status="coming_soon",
        icon="inventory",
    ),
    ModuleInfo(
        id="payments",
        title="Material Payments",
        description="Pay suppliers — full or partial — linked to purchases",
        status="coming_soon",
        icon="payments",
    ),
    ModuleInfo(
        id="labour",
        title="Labour & Salary",
        description="Wages, weekly advances, and monthly salary settlement",
        status="coming_soon",
        icon="groups",
    ),
    ModuleInfo(
        id="fish_catch",
        title="Fish Catch Sales",
        description="Catch events, vehicle sales, fish type weight & rates",
        status="coming_soon",
        icon="set_meal",
    ),
    ModuleInfo(
        id="feed_prep",
        title="Feed Preparation",
        description="Prepare feed from materials and send to fish tanks",
        status="coming_soon",
        icon="factory",
    ),
    ModuleInfo(
        id="expenses",
        title="Expenses",
        description="Track all factory expenses by month",
        status="coming_soon",
        icon="trending_down",
    ),
    ModuleInfo(
        id="income",
        title="Income",
        description="Income from fish sales and other sources",
        status="coming_soon",
        icon="trending_up",
    ),
    ModuleInfo(
        id="investments",
        title="Investments",
        description="Capital and investment tracking",
        status="coming_soon",
        icon="account_balance",
    ),
    ModuleInfo(
        id="reports",
        title="Monthly Reports",
        description="Month-wise P&L: materials, labour, catch income",
        status="coming_soon",
        icon="assessment",
    ),
]


@router.get("", response_model=ModulesResponse)
def list_modules() -> ModulesResponse:
    return ModulesResponse(modules=FACTORY_MODULES)
