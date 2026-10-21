from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse

from agent.fixtures import FIXTURE_DIR, load_bi_case

UI_FILE = Path(__file__).resolve().parents[1] / "ui" / "index.html"
app = FastAPI()


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(UI_FILE, media_type="text/html; charset=utf-8")


@app.get("/api/cases")
def list_cases() -> list[dict[str, Any]]:
    rows = json.loads((FIXTURE_DIR / "bi_inputs.json").read_text(encoding="utf-8"))
    return [
        {
            "case_id": row["case_id"],
            "group": row.get("group"),
            "title": row.get("title"),
            "status": row.get("raw_status"),
            "reason": row.get("raw_reason"),
        }
        for row in rows
    ]


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> dict[str, Any]:
    try:
        return jsonable_encoder(load_bi_case(case_id))
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown synthetic case ID") from None
