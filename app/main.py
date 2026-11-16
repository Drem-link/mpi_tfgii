from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile as StarletteUploadFile

from app import dbfio
from app import xlsxio
from app.shapefile import MAX_ARCHIVE_BYTES, ShapefileDataset, load_shapefile_zip
from app.textutil import fold

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"
DATASET_PATH = Path(os.environ.get("MPI_DATASET_PATH", PROJECT_ROOT / "data" / "deposits.zip"))
_dataset: ShapefileDataset | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _dataset
    if DATASET_PATH.is_file():
        with DATASET_PATH.open("rb") as source:
            _dataset = load_shapefile_zip(DATASET_PATH.name, source)
    yield


app = FastAPI(title="Месторождения", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _require_dataset() -> ShapefileDataset:
    if _dataset is None:
        raise HTTPException(503, "Сначала загрузите ZIP-архив шейпа.")
    return _dataset


def _export_rows(records) -> bytes:
    return dbfio.dumps(
        [{field[0]: record.canonical.get(field[0]) for field in dbfio.FIELDS} for record in records]
    )


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def status():
    return {"loaded": _dataset is not None, "dataset": _dataset.summary() if _dataset else None}


@app.get("/api/map")
def map_overview():
    dataset = _require_dataset()
    return {
        "items": [
            {
                "id": record.id,
                "name": record.name,
                "lat": record.center["lat"],
                "lon": record.center["lon"],
            }
            for record in dataset.records
            if record.center
        ]
    }


@app.post("/api/dataset")
async def upload_dataset(request: Request):
    global _dataset
    async with request.form(
        max_files=1, max_fields=0, max_part_size=MAX_ARCHIVE_BYTES
    ) as form:
        file = form.get("file")
        if not isinstance(file, StarletteUploadFile):
            raise HTTPException(400, "Выберите ZIP-архив.")
        filename = Path((file.filename or "").replace("\\", "/")).name
        if not filename.lower().endswith(".zip"):
            raise HTTPException(400, "Загрузите ZIP-архив с файлами .shp, .dbf и желательно .prj.")
        temporary_path = None
        try:
            DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                prefix=".deposits-", suffix=".zip", dir=DATASET_PATH.parent, delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                total_size = 0
                while chunk := await file.read(1024 * 1024):
                    total_size += len(chunk)
                    if total_size > MAX_ARCHIVE_BYTES:
                        raise HTTPException(413, "ZIP-архив больше 512 МБ.")
                    temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())

            with temporary_path.open("rb") as source:
                try:
                    loaded = await asyncio.to_thread(load_shapefile_zip, filename, source)
                except ValueError as error:
                    raise HTTPException(400, str(error)) from error
            os.replace(temporary_path, DATASET_PATH)
            _dataset = loaded
            return {
                "dataset": loaded.summary(),
                "items": [record.as_dict(include_geometry=False) for record in loaded.records[:80]],
            }
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()


@app.get("/api/occurrences")
def occurrences(
    q: str = Query("", max_length=200),
    offset: int = Query(0, ge=0),
    limit: int = Query(80, ge=1, le=200),
):
    dataset = _require_dataset()
    query = fold(q)
    matching = [
        record
        for record in dataset.records
        if not query
        or query in fold(record.name)
        or any(query in fold(str(value)) for value in record.attributes.values() if value is not None)
    ]
    return {
        "dataset": dataset.summary(),
        "total": len(matching),
        "offset": offset,
        "limit": limit,
        "items": [record.as_dict(include_geometry=False) for record in matching[offset : offset + limit]],
    }


@app.get("/api/occurrences/{record_id}")
def occurrence(record_id: int):
    dataset = _require_dataset()
    if record_id < 0 or record_id >= len(dataset.records):
        raise HTTPException(404, "Месторождение не найдено.")
    return dataset.records[record_id].as_dict()


@app.get("/api/export/dbf")
def export_dbf(record_id: int | None = None):
    dataset = _require_dataset()
    if record_id is None:
        records = dataset.records
        filename = "occurrences.dbf"
    else:
        if record_id < 0 or record_id >= len(dataset.records):
            raise HTTPException(404, "Месторождение не найдено.")
        records = [dataset.records[record_id]]
        filename = f"occurrence-{record_id + 1}.dbf"
    return Response(
        content=_export_rows(records),
        media_type="application/x-dbase",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export/xlsx")
def export_xlsx(record_id: int | None = None):
    dataset = _require_dataset()
    if record_id is None:
        records = dataset.records
        filename = "occurrences.xlsx"
    else:
        if record_id < 0 or record_id >= len(dataset.records):
            raise HTTPException(404, "Месторождение не найдено.")
        records = [dataset.records[record_id]]
        filename = f"occurrence-{record_id + 1}.xlsx"
    return Response(
        content=xlsxio.dumps(dataset.fields, (record.attributes for record in records)),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
