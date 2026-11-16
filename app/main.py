from __future__ import annotations

import asyncio
import os
import re
import secrets
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.middleware.sessions import SessionMiddleware

from app import dbfio, xlsxio
from app.accounts import AccountStore
from app.shapefile import MAX_ARCHIVE_BYTES, ShapefileDataset, load_shapefile_zip
from app.textutil import fold

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"
DATASET_PATH = Path(os.environ.get("MPI_DATASET_PATH", PROJECT_ROOT / "data" / "deposits.zip"))
DATA_ROOT = DATASET_PATH.parent
ACCOUNT_DB_PATH = DATA_ROOT / "private" / "accounts.sqlite3"
USER_DATASETS_DIR = DATA_ROOT / "users"
_store = AccountStore(ACCOUNT_DB_PATH)
_dataset: ShapefileDataset | None = None
_dataset_cache: dict[str, ShapefileDataset] = {}
_upload_lock = asyncio.Lock()
_USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{3,32}\Z")
MAX_PRIVATE_DATASETS = 20
MAX_PRIVATE_DATA_BYTES = 768 * 1024 * 1024


def _session_secret() -> str:
    configured = os.environ.get("MPI_SESSION_SECRET")
    if configured:
        if len(configured) < 32:
            raise RuntimeError("MPI_SESSION_SECRET must be at least 32 characters.")
        return configured
    path = DATA_ROOT / ".session-secret"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        secret = path.read_text(encoding="ascii").strip()
        if len(secret) < 32:
            raise RuntimeError(f"Session secret at {path} is missing or too short.")
        return secret
    secret = secrets.token_urlsafe(48)
    with os.fdopen(descriptor, "w", encoding="ascii") as output:
        output.write(secret)
        output.flush()
        os.fsync(output.fileno())
    return secret


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _dataset
    _store.initialize()
    _dataset_cache.clear()
    _dataset = None
    if DATASET_PATH.is_file():
        with DATASET_PATH.open("rb") as source:
            _dataset = load_shapefile_zip(DATASET_PATH.name, source)
        _dataset_cache["shared"] = _dataset
    yield


app = FastAPI(title="Месторождения", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret(),
    session_cookie="mpi_session",
    max_age=12 * 60 * 60,
    same_site="lax",
    https_only=os.environ.get("MPI_COOKIE_SECURE", "").casefold() in {"1", "true", "yes"},
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def prevent_api_caching(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "Cookie"
    return response


def _session(request: Request) -> dict:
    return request.scope.setdefault("session", {})


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    try:
        parsed = urlsplit(origin)
    except ValueError as error:
        raise HTTPException(403, "Запрос отклонён: неверный источник.") from error
    host = request.headers.get("host", "")
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.netloc.casefold() != host.casefold()
    ):
        raise HTTPException(403, "Запрос отклонён: источник не совпадает с сайтом.")


def _credentials(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict):
        raise HTTPException(400, "Передайте логин и пароль.")
    username = payload.get("username")
    password = payload.get("password")
    if not isinstance(username, str) or not _USERNAME_PATTERN.fullmatch(username):
        raise HTTPException(400, "Логин: от 3 до 32 символов — латинские буквы, цифры, точка, дефис или _.")
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise HTTPException(400, "Пароль должен содержать от 12 до 128 символов.")
    return username, password


def _require_user(request: Request) -> dict[str, str]:
    user_id = _session(request).get("user_id")
    user = _store.get_user(user_id) if isinstance(user_id, str) else None
    if user is None:
        raise HTTPException(401, "Войдите в кабинет.")
    return user


def _dataset_summary(
    dataset: ShapefileDataset,
    *,
    dataset_id: str,
    name: str,
    shared: bool,
) -> dict:
    summary = dataset.summary()
    summary.update({"id": dataset_id, "name": name, "shared": shared})
    return summary


def _cache_dataset(dataset_id: str, dataset: ShapefileDataset) -> ShapefileDataset:
    _dataset_cache.pop(dataset_id, None)
    _dataset_cache[dataset_id] = dataset
    while sum(key != "shared" for key in _dataset_cache) > 2:
        oldest = next(key for key in _dataset_cache if key != "shared" and key != dataset_id)
        _dataset_cache.pop(oldest)
    return dataset


def _shared_dataset() -> ShapefileDataset:
    if _dataset is None:
        raise HTTPException(503, "Данные не загружены.")
    return _dataset


def _require_dataset(request: Request) -> ShapefileDataset:
    session = _session(request)
    dataset_id = session.get("active_dataset_id", "shared")
    if dataset_id == "shared":
        return _shared_dataset()

    user_id = session.get("user_id")
    if not isinstance(dataset_id, str) or not isinstance(user_id, str):
        session["active_dataset_id"] = "shared"
        return _shared_dataset()
    row = _store.get_dataset(dataset_id, user_id)
    if row is None:
        session["active_dataset_id"] = "shared"
        return _shared_dataset()

    cached = _dataset_cache.get(dataset_id)
    if cached is not None:
        return cached
    path = USER_DATASETS_DIR / user_id / f"{dataset_id}.zip"
    if not path.is_file():
        raise HTTPException(500, "Файл личного набора не найден на хранилище.")
    with path.open("rb") as source:
        try:
            loaded = load_shapefile_zip(row["source_filename"], source)
        except ValueError as error:
            raise HTTPException(500, "Не удалось прочитать сохранённый личный набор.") from error
    loaded.filename = row["name"]
    return _cache_dataset(dataset_id, loaded)


def _active_dataset_id(request: Request) -> str | None:
    dataset_id = _session(request).get("active_dataset_id", "shared")
    if dataset_id == "shared":
        return "shared" if _dataset is not None else None
    user_id = _session(request).get("user_id")
    if isinstance(dataset_id, str) and isinstance(user_id, str):
        if _store.get_dataset(dataset_id, user_id):
            return dataset_id
    _session(request)["active_dataset_id"] = "shared"
    return "shared" if _dataset is not None else None


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


@app.post("/api/auth/register")
async def register(request: Request):
    _check_origin(request)
    try:
        payload = await request.json()
    except ValueError as error:
        raise HTTPException(400, "Некорректный запрос.") from error
    username, password = _credentials(payload)
    user = await asyncio.to_thread(_store.create_user, username, password)
    if user is None:
        raise HTTPException(409, "Такой логин уже занят.")
    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["active_dataset_id"] = "shared"
    return {"user": {"id": user["id"], "username": user["username"]}}


@app.post("/api/auth/login")
async def login(request: Request):
    _check_origin(request)
    try:
        payload = await request.json()
    except ValueError as error:
        raise HTTPException(400, "Некорректный запрос.") from error
    username, password = _credentials(payload)
    user = await asyncio.to_thread(_store.authenticate, username, password)
    if user is None:
        raise HTTPException(401, "Неверный логин или пароль.")
    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["active_dataset_id"] = "shared"
    return {"user": user}


@app.get("/api/auth/me")
def current_account(request: Request):
    user_id = _session(request).get("user_id")
    user = _store.get_user(user_id) if isinstance(user_id, str) else None
    if user is None:
        _session(request).clear()
    return {"user": user}


@app.post("/api/auth/logout")
def logout(request: Request):
    _check_origin(request)
    request.session.clear()
    return {"ok": True}


@app.get("/api/datasets")
def list_datasets(request: Request):
    items = []
    if _dataset is not None:
        items.append(
            {
                "id": "shared",
                "name": "Общий каталог",
                "shared": True,
                "count": len(_dataset.records),
            }
        )
    user_id = _session(request).get("user_id")
    if isinstance(user_id, str):
        items.extend(
            {
                "id": row["id"],
                "name": row["name"],
                "shared": False,
                "count": row["record_count"],
            }
            for row in _store.list_datasets(user_id)
        )
    return {"items": items, "active_id": _active_dataset_id(request)}


@app.post("/api/datasets/{dataset_id}/select")
def select_dataset(dataset_id: str, request: Request):
    _check_origin(request)
    if dataset_id == "shared":
        _shared_dataset()
    else:
        user = _require_user(request)
        if _store.get_dataset(dataset_id, user["id"]) is None:
            raise HTTPException(404, "Набор не найден.")
    request.session["active_dataset_id"] = dataset_id
    return {"datasets": list_datasets(request)}


async def _upload_dataset(request: Request):
    _check_origin(request)
    user = _require_user(request)
    async with request.form(
        max_files=1, max_fields=0, max_part_size=MAX_ARCHIVE_BYTES
    ) as form:
        file = form.get("file")
        if not isinstance(file, StarletteUploadFile):
            raise HTTPException(400, "Выберите ZIP-архив.")
        filename = Path((file.filename or "").replace("\\", "/")).name
        if not filename.lower().endswith(".zip"):
            raise HTTPException(400, "Загрузите ZIP-архив с файлами .shp, .dbf и желательно .prj.")
        name = Path(filename).stem.strip()[:80]
        if not name:
            name = "Мой шейп"

        file.file.seek(0, 2)
        archive_size = file.file.tell()
        file.file.seek(0)
        if archive_size > MAX_ARCHIVE_BYTES:
            raise HTTPException(413, "ZIP-архив больше 512 МБ.")
        async with _upload_lock:
            if len(_store.list_datasets(user["id"])) >= MAX_PRIVATE_DATASETS:
                raise HTTPException(
                    409, f"Можно хранить не больше {MAX_PRIVATE_DATASETS} личных наборов."
                )
            stored_bytes = sum(
                path.stat().st_size
                for path in USER_DATASETS_DIR.rglob("*.zip")
                if path.is_file()
            )
            if stored_bytes + archive_size > MAX_PRIVATE_DATA_BYTES:
                raise HTTPException(413, "Общий объём личных шейпов превысит лимит 768 МБ.")
            return await _persist_upload(request, user, file, filename, name)


async def _persist_upload(request, user, file, filename: str, name: str):
    dataset_id = uuid.uuid4().hex
    directory = USER_DATASETS_DIR / user["id"]
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(USER_DATASETS_DIR, 0o700)
    os.chmod(directory, 0o700)
    final_path = directory / f"{dataset_id}.zip"
    temporary_path = None
    stored = False
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{dataset_id}-", suffix=".zip", dir=directory, delete=False
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
        loaded.filename = name
        os.replace(temporary_path, final_path)
        temporary_path = None
        await asyncio.to_thread(
            _store.create_dataset,
            dataset_id,
            user["id"],
            name,
            filename,
            len(loaded.records),
        )
        stored = True
        _cache_dataset(dataset_id, loaded)
        request.session["active_dataset_id"] = dataset_id
        return {
            "dataset": _dataset_summary(loaded, dataset_id=dataset_id, name=name, shared=False),
            "items": [record.as_dict(include_geometry=False) for record in loaded.records[:80]],
            "datasets": list_datasets(request),
        }
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
        if not stored and final_path.exists():
            final_path.unlink()


@app.post("/api/datasets")
async def upload_dataset(request: Request):
    return await _upload_dataset(request)


@app.post("/api/dataset")
async def upload_dataset_legacy(request: Request):
    return await _upload_dataset(request)


@app.patch("/api/datasets/{dataset_id}")
async def rename_dataset(dataset_id: str, request: Request):
    _check_origin(request)
    user = _require_user(request)
    try:
        payload = await request.json()
    except ValueError as error:
        raise HTTPException(400, "Некорректный запрос.") from error
    name = payload.get("name") if isinstance(payload, dict) else None
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise HTTPException(400, "Название должно содержать от 1 до 80 символов.")
    name = name.strip()
    row = _store.get_dataset(dataset_id, user["id"])
    if row is None:
        raise HTTPException(404, "Набор не найден.")
    if not await asyncio.to_thread(_store.rename_dataset, dataset_id, user["id"], name):
        raise HTTPException(404, "Набор не найден.")
    cached = _dataset_cache.get(dataset_id)
    if cached is not None:
        cached.filename = name
    return {"datasets": list_datasets(request)}


@app.delete("/api/datasets/{dataset_id}")
def delete_dataset(dataset_id: str, request: Request):
    _check_origin(request)
    user = _require_user(request)
    row = _store.get_dataset(dataset_id, user["id"])
    if row is None:
        raise HTTPException(404, "Набор не найден.")
    path = USER_DATASETS_DIR / user["id"] / f"{dataset_id}.zip"
    if path.exists():
        path.unlink()
    if not _store.delete_dataset(dataset_id, user["id"]):
        raise HTTPException(404, "Набор не найден.")
    _dataset_cache.pop(dataset_id, None)
    if _session(request).get("active_dataset_id") == dataset_id:
        _session(request)["active_dataset_id"] = "shared"
    return {"datasets": list_datasets(request)}


@app.get("/api/map")
def map_overview(request: Request):
    dataset = _require_dataset(request)
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


@app.get("/api/occurrences")
def occurrences(
    request: Request,
    q: str = Query("", max_length=200),
    offset: int = Query(0, ge=0),
    limit: int = Query(80, ge=1, le=200),
):
    dataset = _require_dataset(request)
    query = fold(q)
    matching = [
        record
        for record in dataset.records
        if not query
        or query in fold(record.name)
        or any(query in fold(str(value)) for value in record.attributes.values() if value is not None)
    ]
    active_id = _active_dataset_id(request) or "shared"
    if active_id == "shared":
        name = "Общий каталог"
        shared = True
    else:
        user = _require_user(request)
        row = _store.get_dataset(active_id, user["id"])
        if row is None:
            raise HTTPException(404, "Набор не найден.")
        name = row["name"]
        shared = False
    return {
        "dataset": _dataset_summary(
            dataset, dataset_id=active_id, name=name, shared=shared
        ),
        "total": len(matching),
        "offset": offset,
        "limit": limit,
        "items": [record.as_dict(include_geometry=False) for record in matching[offset : offset + limit]],
    }


@app.get("/api/occurrences/{record_id}")
def occurrence(record_id: int, request: Request):
    dataset = _require_dataset(request)
    if record_id < 0 or record_id >= len(dataset.records):
        raise HTTPException(404, "Месторождение не найдено.")
    return dataset.records[record_id].as_dict()


@app.get("/api/export/dbf")
def export_dbf(request: Request, record_id: int | None = None):
    dataset = _require_dataset(request)
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
def export_xlsx(request: Request, record_id: int | None = None):
    dataset = _require_dataset(request)
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
