from ninja import NinjaAPI

from api.routes import devel, releng

api = NinjaAPI(
    version="1",
    title="Archweb API",
    description="Arch Linux web API",
    openapi_url="/openapi.json",
    docs_url="/docs/",
)

api.add_router("/v1/releng/", releng.router)
api.add_router("/v1/devel/", devel.router)
