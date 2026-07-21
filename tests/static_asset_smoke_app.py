from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from server.static_assets import ROOT, StaticAssetVersionMiddleware

app = FastAPI()
app.add_middleware(StaticAssetVersionMiddleware)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((ROOT / "web" / "index.html").read_text(encoding="utf-8"))


app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
