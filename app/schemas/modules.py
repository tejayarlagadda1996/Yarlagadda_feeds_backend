from pydantic import BaseModel


class ModuleInfo(BaseModel):
    id: str
    title: str
    description: str
    status: str  # ready | coming_soon
    icon: str


class ModulesResponse(BaseModel):
    modules: list[ModuleInfo]
