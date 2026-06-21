import os
import time
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import chromadb
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# --- НАСТРОЙКИ ---

# --- НАСТРОЙКИ ---
VAULT_PATH = r"C:\Users\kiiittto\Documents\Obsidian Vault"  # ЗАМЕНИ НА СВОЙ ПУТЬ
DEBOUNCE_DELAY = 5.0  # Ждем 5 секунд после последнего изменения файла
CHROMA_PATH = "./chroma_db"
OLLAMA_MODEL = "qwen2:7b"  # Модель для эмбеддингов (которую мы обсуждали)

# Инициализация базы и эмбеддингов
print("Подключение к ChromaDB и Ollama...")
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="obsidian_vault")
embeddings_model = OllamaEmbeddings(model=OLLAMA_MODEL)

# Текст-сплиттер для разбивки больших заметок на чанки
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    separators=["\n\n", "\n", " ", ""]
)

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ДЛЯ DEBOUNCE ---
pending_files = {}  # Формат: { "путь_к_файлу": timestamp_последнего_изменения }
lock = threading.Lock()


class ObsidianEventHandler(FileSystemEventHandler):
    """Слушает события файловой системы и ставит файлы в очередь."""

    def _is_valid(self, path):
        # Пропускаем файлы, если в их пути есть скрытые папки (начинающиеся с точки)
        if '\\.' in path or '/.' in path:
            return False
        return path.endswith('.md')

    def on_modified(self, event):
        if not event.is_directory and self._is_valid(event.src_path):
            with lock:
                pending_files[event.src_path] = time.time()
                print(f"[✏️ Изменение поймано] Ждем {DEBOUNCE_DELAY} сек: {os.path.basename(event.src_path)}")

    def on_created(self, event):
        if not event.is_directory and self._is_valid(event.src_path):
            with lock:
                pending_files[event.src_path] = time.time()

    def on_deleted(self, event):
        if not event.is_directory and self._is_valid(event.src_path):
            file_path = event.src_path
            with lock:
                if file_path in pending_files:
                    del pending_files[file_path]

            print(f"[🗑️ Удаление] Очистка индекса для: {os.path.basename(file_path)}")
            collection.delete(where={"source": file_path})


def process_file(file_path):
    """Основная логика индексации файла."""
    try:
        # Проверяем, существует ли файл (мог быть удален, пока мы ждали)
        if not os.path.exists(file_path):
            return

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Пропускаем пустые файлы
        if not content.strip():
            return

        filename = os.path.basename(file_path)
        print(f"[⚙️ Индексация] Запуск векторизации: {filename}...")

        # 1. Удаляем старые чанки этого файла из базы (если они были)
        collection.delete(where={"source": file_path})

        # 2. Разбиваем текст на куски
        chunks = text_splitter.split_text(content)

        # 3. Подготавливаем данные для ChromaDB
        documents = []
        metadatas = []
        ids = []

        for i, chunk in enumerate(chunks):
            documents.append(chunk)
            metadatas.append({"source": file_path, "filename": filename})
            ids.append(f"{file_path}_chunk_{i}")

        # 4. Сохраняем в базу (upsert сам сгенерирует векторы через Ollama, если настроить функцию встраивания, 
        # но надежнее сгенерировать их через LangChain и передать)

        # Генерируем векторы напрямую через OllamaEmbeddings
        embeddings = embeddings_model.embed_documents(documents)

        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )
        print(f"[✅ Успех] Файл {filename} сохранен в базу ({len(chunks)} чанков).")

    except Exception as e:
        print(f"[❌ Ошибка] Не удалось обработать {file_path}: {e}")


def debounce_worker():
    """Фоновый поток, который проверяет очередь и запускает индексацию."""
    while True:
        time.sleep(1)  # Проверяем очередь каждую секунду
        current_time = time.time()
        files_to_process = []

        with lock:
            # Ищем файлы, которые не менялись дольше DEBOUNCE_DELAY
            for file_path, last_modified in list(pending_files.items()):
                if current_time - last_modified > DEBOUNCE_DELAY:
                    files_to_process.append(file_path)
                    del pending_files[file_path]  # Убираем из очереди

        # Обрабатываем файлы вне блокировки, чтобы не тормозить прием новых событий
        for file_path in files_to_process:
            process_file(file_path)


def sync_all_files_on_startup():
    """Сканирует всю базу знаний при запуске, игнорируя системные папки."""
    print("\n[🔄 Синхронизация] Поиск существующих файлов в базе...")
    count = 0

    for root, dirs, files in os.walk(VAULT_PATH):
        # МАГИЯ ЗДЕСЬ: Выкидываем из сканирования все папки, начинающиеся с точки (.obsidian, .trash)
        dirs[:] = [d for d in dirs if not d.startswith('.')]

        for file in files:
            # Берем только .md файлы и тоже игнорируем файлы, начинающиеся с точки
            if file.endswith('.md') and not file.startswith('.'):
                file_path = os.path.join(root, file)

                with lock:
                    pending_files[file_path] = 0
                count += 1

    print(f"[🔄 Синхронизация] Найдено {count} полезных заметок. Они добавлены в очередь.\n")


if __name__ == "__main__":
    if not os.path.exists(VAULT_PATH):
        print(f"ОШИБКА: Папка {VAULT_PATH} не найдена. Проверьте путь.")
        exit(1)

    # 1. Запускаем фоновый поток для обработки очереди
    worker = threading.Thread(target=debounce_worker, daemon=True)
    worker.start()

    # 2. НОВОЕ: Запускаем полную проверку всех файлов при старте
    sync_all_files_on_startup()

    # 3. Запускаем наблюдателя за файловой системой (слушает новые изменения)
    event_handler = ObsidianEventHandler()
    observer = Observer()
    observer.schedule(event_handler, path=VAULT_PATH, recursive=True)
    observer.start()

    print(f"🚀 Служба индексации запущена.")
    print(f"📁 Отслеживается папка: {VAULT_PATH}")
    print(f"⏱️ Задержка автосохранения (Debounce): {DEBOUNCE_DELAY} сек.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nОстановка службы...")
        observer.stop()

    observer.join()