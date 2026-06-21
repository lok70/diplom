import { App, Editor, MarkdownView, Notice, Plugin, PluginSettingTab, Setting } from 'obsidian';

// Интерфейс настроек
interface ChatFormatterSettings {
    targetFolder: string;
    startMarkers: string;
    endMarkers: string;
}

const DEFAULT_SETTINGS: ChatFormatterSettings = {
    targetFolder: "Ответы ИИ",
    startMarkers: "(((, **ИИ**:", // Можно перечислять маркеры через запятую
    endMarkers: "))), ---"
}

export default class ChatFormatterPlugin extends Plugin {
    settings: ChatFormatterSettings;

    async onload() {
        await this.loadSettings();
        this.addSettingTab(new ChatFormatterSettingTab(this.app, this));

        this.addCommand({
            id: 'format-nested-callouts-copy',
            name: 'Оформить (создать копию)',
            editorCallback: async (editor: Editor, view: MarkdownView) => {
                await this.formatChat(editor, view);
            }
        });

        this.registerEvent(
            this.app.workspace.on('editor-menu', (menu, editor, view) => {
                menu.addItem((item) => {
                    item
                        .setTitle('Оформить (копия)')
                        .setIcon('help-circle')
                        .onClick(() => {
                            this.formatChat(editor, view);
                        });
                });
            })
        );

        this.addRibbonIcon('help-circle', 'Оформить (копия)', (evt: MouseEvent) => {
            const view = this.app.workspace.getActiveViewOfType(MarkdownView);
            if (view && view.editor) {
                this.formatChat(view.editor, view);
            } else {
                new Notice('Пожалуйста, откройте заметку!');
            }
        });
    }

    async formatChat(editor: Editor, view: MarkdownView) {
        const currentFile = view.file;
        if (!currentFile) return;

        const targetFolder = this.settings.targetFolder.trim();
        if (!targetFolder) {
            new Notice("Укажите папку в настройках!");
            return;
        }

        const fullContent = editor.getValue();
        let yaml = "";
        let chatBody = fullContent;

        // Сохраняем YAML (свойства заметки), если они есть
        if (fullContent.trimStart().startsWith("---")) {
            const parts = fullContent.split(/^---/m);
            if (parts.length >= 3) {
                yaml = `---${parts[1]}---\n`;
                chatBody = parts.slice(2).join("---").trim();
            }
        }

        // Подготавливаем массивы маркеров
        const starts = this.settings.startMarkers.split(',').map(s => s.trim()).filter(s => s);
        const ends = this.settings.endMarkers.split(',').map(s => s.trim()).filter(s => s);

        if (starts.length === 0 || ends.length === 0) {
            new Notice("Ошибка: добавьте маркеры в настройки!");
            return;
        }

        // Изолируем ВСЕ маркеры на отдельные строки
        let safeBody = chatBody;
        starts.forEach(m => safeBody = safeBody.split(m).join(`\n${m}\n`));
        ends.forEach(m => safeBody = safeBody.split(m).join(`\n${m}\n`));

        const rawLines = safeBody.split(/\r?\n/);
        let finalOutputLines: string[] = [];
        let depth = 0;
        let needsTitle = false;

        for (let i = 0; i < rawLines.length; i++) {
            let line = rawLines[i];
            let trimmed = line.trim();

            // Проверка на маркер НАЧАЛА
            if (starts.includes(trimmed)) {
                depth++;
                needsTitle = true;
                continue;
            } 
            // Проверка на маркер КОНЦА
            else if (ends.includes(trimmed)) {
                if (depth > 0) {
                    depth--;
                    // ВАЖНО: Добавляем пустую строку, чтобы разорвать Markdown-блок цитаты
                    finalOutputLines.push(""); 
                }
                continue;
            }

            let prefix = "> ".repeat(depth);
            
            // Обработка пустых строк
            if (!trimmed) {
                // ИСПРАВЛЕНИЕ: Если мы ждем заголовок, просто пропускаем пустые строки, 
                // чтобы не сломать синтаксис Callout-блока!
                if (needsTitle) continue; 
                
                if (depth > 0) finalOutputLines.push(prefix.trimEnd());
                else finalOutputLines.push("");
                continue;
            }

            // Обработка первой строки внутри нового блока (создание Callout)
            if (needsTitle) {
                // Берем первые 5 слов для красивого заголовка
                let titleWords = trimmed.split(' ').slice(0, 5).join(' ');
                let title = titleWords + (trimmed.length > titleWords.length ? "..." : "");
                
                // Создаем шапку свернутого блока
                finalOutputLines.push(`${prefix.slice(0, -2)}> [!note]- Ответ: ${title}`);
                // Помещаем саму строку внутрь тела блока
                finalOutputLines.push(`${prefix}${line}`);
                needsTitle = false;
            } else {
                // Обычные строки внутри блока или снаружи
                finalOutputLines.push(`${prefix}${line}`);
            }
        }

        const finalOutput = yaml + (yaml ? "\n" : "") + finalOutputLines.join("\n").replace(/\n{3,}/g, '\n\n');

        try {
            let folder = this.app.vault.getAbstractFileByPath(targetFolder);
            if (!folder) await this.app.vault.createFolder(targetFolder);

            let newPath = `${targetFolder}/${currentFile.basename}_formatted.${currentFile.extension}`;
            let counter = 1;
            while (this.app.vault.getAbstractFileByPath(newPath)) {
                newPath = `${targetFolder}/${currentFile.basename}_formatted_${counter}.${currentFile.extension}`;
                counter++;
            }

            await this.app.vault.create(newPath, finalOutput);
            new Notice(`Готово! Отформатировано в: ${newPath}`);
        } catch (err) {
            console.error(err);
            new Notice("Ошибка сохранения!");
        }
    }

    async loadSettings() {
        this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
    }

    async saveSettings() {
        await this.saveData(this.settings);
    }
}

class ChatFormatterSettingTab extends PluginSettingTab {
    plugin: ChatFormatterPlugin;

    constructor(app: App, plugin: ChatFormatterPlugin) {
        super(app, plugin);
        this.plugin = plugin;
    }

    display(): void {
        const {containerEl} = this;
        containerEl.empty();
        containerEl.createEl('h2', {text: 'Настройки Chat Formatter'});

        new Setting(containerEl)
            .setName('Папка для сохранения')
            .addText(text => text
                .setValue(this.plugin.settings.targetFolder)
                .onChange(async (value) => {
                    this.plugin.settings.targetFolder = value;
                    await this.plugin.saveSettings();
                }));

        new Setting(containerEl)
            .setName('Маркеры начала')
            .setDesc('Введите маркеры через запятую (например: (((, **ИИ**:)')
            .addText(text => text
                .setValue(this.plugin.settings.startMarkers)
                .onChange(async (value) => {
                    this.plugin.settings.startMarkers = value;
                    await this.plugin.saveSettings();
                }));

        new Setting(containerEl)
            .setName('Маркеры конца')
            .setDesc('Введите маркеры через запятую (например: ))), ---)')
            .addText(text => text
                .setValue(this.plugin.settings.endMarkers)
                .onChange(async (value) => {
                    this.plugin.settings.endMarkers = value;
                    await this.plugin.saveSettings();
                }));
    }
}