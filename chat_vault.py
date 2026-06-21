import chromadb
from langchain_ollama import OllamaLLM, OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder  # ДОБАВЛЕНО
from langchain_core.messages import HumanMessage, AIMessage  # ДОБАВЛЕНО
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_classic.chains import create_retrieval_chain

CHROMA_PATH = "./chroma_db"
EMBEDDING_MODEL = "qwen2:7b"


class VaultChatBot:
    def __init__(self):
        print("Инициализация ядра RAG...")

        self.chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        self.embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL)

        self.vector_store = Chroma(
            client=self.chroma_client,
            collection_name="obsidian_vault",
            embedding_function=self.embeddings
        )
        self.retriever = self.vector_store.as_retriever(search_kwargs={"k": 4})

        self.system_prompt = (
            "Ты — умный ИИ-ассистент, встроенный в личную базу знаний (Obsidian) пользователя. "
            "Твоя задача — отвечать на вопросы, используя ТОЛЬКО предоставленный контекст из заметок пользователя.\n\n"
            "Контекст:\n{context}\n\n"
            "Правила:\n"
            "1. Если ответа нет в контексте, честно скажи: 'В вашей базе знаний нет информации об этом'. Не выдумывай факты.\n"
            "2. Отвечай на том же языке, на котором задан вопрос.\n"
            "3. Форматируй ответ красиво, используя Markdown.\n"
            "4. Учитывай историю предыдущих сообщений диалога.\n"  # ДОБАВЛЕНО ПРАВИЛО
        )

        # ДОБАВЛЕН MessagesPlaceholder ДЛЯ ИСТОРИИ
        self.prompt_template = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{input}"),
        ])
        print("✅ Модуль RAG готов к работе!")

    # ДОБАВЛЕН АРГУМЕНТ history
    def ask(self, user_query: str, model_name: str, history: list = None):
        if history is None:
            history = []

        print(f"\n[?] Вопрос: {user_query}")
        print(f"[*] Генерирую ответ с помощью модели: {model_name} ...")

        # Превращаем словари из TypeScript в объекты LangChain
        langchain_history = []
        for msg in history:
            if msg.get("role") == "user":
                langchain_history.append(HumanMessage(content=msg.get("content")))
            elif msg.get("role") == "assistant":
                langchain_history.append(AIMessage(content=msg.get("content")))

        llm = OllamaLLM(model=model_name)

        question_answer_chain = create_stuff_documents_chain(llm, self.prompt_template)
        rag_chain = create_retrieval_chain(self.retriever, question_answer_chain)

        # ПЕРЕДАЕМ ИСТОРИЮ ПРИ ЗАПУСКЕ ЦЕПОЧКИ
        response = rag_chain.invoke({
            "input": user_query,
            "history": langchain_history
        })

        answer = response["answer"]
        source_documents = response["context"]

        sources = set([doc.metadata.get("filename", "Неизвестный файл") for doc in source_documents])

        return {
            "answer": answer,
            "sources": list(sources)
        }