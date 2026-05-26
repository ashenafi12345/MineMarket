import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from database import Base, engine
from routers import auth, chat, comments, favorites, products, users


# =========================================
# CREATE TABLES
# =========================================
Base.metadata.create_all(bind=engine)


# =========================================
# APP
# =========================================
app = FastAPI(title="MineMarket API")


# =========================================
# CORS
# =========================================
origins = [
    "http://localhost:3000",
    "https://mine-market-tghv.vercel.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================
# ROUTERS
# =========================================
app.include_router(auth.router)
app.include_router(products.router)
app.include_router(users.router)
app.include_router(favorites.router)
app.include_router(comments.router)
app.include_router(chat.router)



# =========================================
# STATIC FILES (UPLOADS)
# =========================================
UPLOAD_DIR = "uploads"

# IMPORTANT: ensure folder exists
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.mount(
    "/uploads",
    StaticFiles(directory=UPLOAD_DIR),
    name="uploads"
)