# schematic-renderer

CLI-утилита на Python: описание цифровой схемы в YAML превращается в PNG или SVG.
Поддерживаются блоки, выводы, шины, внешние сигналы и соединения. Для сложных
схем доступна автоматическая компоновка слева направо через ELK.

Это **инструмент рисования**, не симулятор электроники. RG, SM, MX, AND и другие
обозначения являются подписями универсальных блоков. Логику определяет автор YAML.

## Быстрый старт

Нужен Python 3.10+ и интернет для установки зависимостей.
Скачайте репозиторий через **Code -> Download ZIP**, распакуйте его и откройте
терминал в папке с `install.py`:

```powershell
python install.py
.venv\Scripts\python.exe -m schematic_renderer examples/simple.yaml -o output/simple.png
```

Установщик создаёт локальную `.venv`, не меняя глобальный Python.
В Windows вместо `python` можно использовать `py -3`. Активация окружения не нужна.

```powershell
python install.py --layout       # также Node.js и ELK для автотрассировки
python install.py --layout --dev # плюс pytest
```

Основной проверяемый сценарий готовых схем: Windows 10/11.
Для Linux/macOS путь к Python окружения: `.venv/bin/python`.
Ограничения по шрифтам и сохранённым координатам описаны в инструкции.

## Документация

- [Установка и запуск](docs/installation.md).
- [Формат YAML: блоки, выводы, соединения и маршруты](docs/yaml-format.md).
- [Разработка и публикация на GitHub](CONTRIBUTING.md).
- [Умножитель с плавающей точкой](docs/float15_functional.md).
- [Умножитель с фиксированной точкой](docs/fixed15_functional.md).

## Примеры

Исходники находятся в `examples`, результаты рендера записываются в `output`.

| YAML | Назначение |
| --- | --- |
| [simple.yaml](examples/simple.yaml) | Небольшая схема |
| [wide_bus.yaml](examples/wide_bus.yaml) | Многоразрядный регистр |
| [register_feedback.yaml](examples/register_feedback.yaml) | Соединения регистров и сумматора |
| [float15_functional.yaml](examples/float15_functional/float15_functional.yaml) | Плавающая точка: 10 бит мантиссы, 5 бит порядка; 15 блоков |
| [fixed15_functional.yaml](examples/fixed15_functional/fixed15_functional.yaml) | Знаковые входы 15 бит / 5 дробных; результат 30 бит / 10 дробных; 9 блоков |

Последние два примера содержат непрерывные внутренние соединения, CLK, RESET,
START, BUSY, READY и отдельный SYNC. Умножение раскрыто функционально, без MUL.
На изображении только схема, без поясняющего текста. Маршруты уже сохранены:
ELK для повторного рендера не нужен.

```powershell
.venv\Scripts\python.exe -m schematic_renderer examples/float15_functional/float15_functional.yaml -o output/float15.png
.venv\Scripts\python.exe -m schematic_renderer examples/fixed15_functional/fixed15_functional.yaml -o output/fixed15.png
```

Для векторного файла замените расширение результата на `.svg`.

## Автоматическая компоновка

После `python install.py --layout`:

```powershell
.venv\Scripts\python.exe -m schematic_renderer.prepare examples/fixed15_functional/fixed15_functional.logic.yaml -o output/fixed15.routed.yaml
.venv\Scripts\python.exe -m schematic_renderer output/fixed15.routed.yaml -o output/fixed15.routed.png
```

Подготовка размещает блоки и сохраняет ортогональные маршруты в YAML.
Она удаляет `primitives`: внешние стрелки готовых примеров нужно добавить по новым
координатам. Для точного повторения готового рисунка используйте основной YAML.

## Разработка

```powershell
python install.py --dev --layout
.venv\Scripts\python.exe -m pytest -q
```

GitHub Actions проверяет Windows с Python 3.10 и 3.12: установка, тесты, рендер,
сборка пакета. `output`, `.venv`, `node_modules` и кэши исключены из Git.

Сохранены также генераторы вентильных схем: `schematic_renderer.assignment15`,
`schematic_renderer.fixed15` и исторический `schematic_renderer.generate`.
Они заново создают результаты в `output`; см. [первое задание](docs/assignment15.md)
и [второе задание](docs/fixed15.md). Крупные варианты требуют ELK.

## Лицензия

[MIT](LICENSE). Зависимости распространяются по собственным лицензиям.
