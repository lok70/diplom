from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any # ДОБАВЛЕНО
from chat_vault import VaultChatBot

app = FastAPI(title="Obsidian AI Assistant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("Запуск AI-сервера...")
bot = VaultChatBot()

# ДОБАВЛЕНО ПОЛЕ history
class QueryRequest(BaseModel):
    question: str
    model: str
    history: List[Dict[str, str]] = [] # По умолчанию пустой список, чтобы не сломать старые запросы

@app.post("/ask")
def ask_question(request: QueryRequest):
    try:
        # ПЕРЕДАЕМ ИСТОРИЮ В ФУНКЦИЮ
        result = bot.ask(request.question, request.model, request.history)

        return {
            "status": "success",
            "answer": result["answer"],
            "sources": result["sources"]
        }
    except Exception as e:
        print(f"Ошибка при генерации ответа: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    print("🚀 API Сервер запущен на http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)